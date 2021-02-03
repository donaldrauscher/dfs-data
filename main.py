import datetime, io, json, os, re, pytz, urllib, warnings

import requests
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from gcsfs import GCSFileSystem
from flask import Flask, request


app = Flask(__name__)
fs = GCSFileSystem(project='blog-180218')

warnings.simplefilter(action='ignore', category=FutureWarning)


def get_current_dt():
    """
    Current datetime in CST
    """
    return pytz.utc.localize(datetime.datetime.utcnow(), is_dst=None).astimezone(pytz.timezone('America/Chicago'))


def rotowire_scrape(dt=None, test=False):
    """
    Download RotoWire player projections
    """
    dt = dt or get_current_dt()

    def process_injury(x):
        try:
            return re.compile(r'<span class="[^"]+">([^<]+)<\/span>').search(x).group(1).upper()
        except AttributeError:
            pass

    response = requests.get(f'https://www.rotowire.com/daily/tables/optimizer-nba.php?sport=NBA&site=DraftKings&projections=&type=main')
    players = (
        pd.DataFrame.from_records(json.loads(response.text))
        .assign(
            player=lambda x: x.player.str.strip(),
            salary=lambda x: x.salary.astype(int),
            is_home=lambda x: (~x.opponent.str.startswith('@')).astype(int),
            opponent=lambda x: x.opponent.str.strip('@'),
            injury_status=lambda x: x.injury.apply(process_injury)
        )
        .rename(columns={'id': 'rw_id'})
    )

    out = f"gs://djr-data/dfs-data/rotowire/projections_{'test' if test else dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        players.to_csv(f, index=False)

    return out


def numberfire_scrape(dt=None, test=False):
    """
    Download NumberFire player projections
    """
    dt = dt or get_current_dt()

    def find_last_name(x):
        s = []
        for w in x.split(' '):
            if w in s:
                return w
            s.append(w)

    def find_first_name(x):
        last_name = x['last_name']
        first_name = re.compile(f'{last_name}\s(.+)\s{last_name}').search(x["player"]).group(1)
        first_name = re.sub('(?:[J|S]r\.?|[VI]+)', '', first_name).strip()
        return first_name

    def find_other(x):
        return re.compile('([A-Z]{1,2})\s+([A-Z]{2,3}) @ ([A-Z]{2,3})(.+)(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)').search(x).groups()

    players_all = []
    for pos in ['g', 'f', 'c']:
        players = pd.read_html(f'https://www.numberfire.com/nba/daily-fantasy/daily-basketball-projections/{pos}',
                               attrs={"class": "stat-table"})[0]

        players.columns = [j.lower() if i.startswith('Unnamed') else f'{i}_{j}'.lower()\
                           for i, j in players.columns.ravel()]
        players = (
            players
            .assign(
                last_name=lambda x: x.player.apply(find_last_name),
                first_name=lambda x: x.apply(find_first_name, axis=1),
                full_name=lambda x: x.first_name + ' ' + x.last_name
            )
        )

        players['pos'], players['team'], players['opp'], players['inj'] = zip(*players.player.apply(find_other))
        players['inj'] = players.inj.str.strip()

        players_all.append(players)


    players = pd.concat(players_all, axis=0, sort=False, ignore_index=True)

    out = f"gs://djr-data/dfs-data/numberfire/projections_{'test' if test else dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        players.to_csv(f, index=False)

    return out


def dfn_scrape(dt=None, test=False):
    """
    Download DFN player projections
    """
    # create browser
    options = webdriver.FirefoxOptions()
    options.headless = True

    profile = webdriver.FirefoxProfile()
    profile.set_preference("browser.download.folderList", 2)
    profile.set_preference("browser.download.manager.showWhenStarting", False)
    profile.set_preference("browser.download.dir", "/tmp")
    profile.set_preference("browser.helperApps.neverAsk.saveToDisk", "text/csv")

    browser = webdriver.Firefox(firefox_profile=profile, options=options)
    browser.implicitly_wait(5)

    # log in
    browser.get('https://dailyfantasynerd.com/login')
    browser.find_element_by_id('input-username').send_keys(os.environ['DFN_USER'])
    browser.find_element_by_id('input-password').send_keys(os.environ['DFN_PASS'])
    browser.find_element_by_xpath("//button[contains(text(),'Sign In')]").click()

    # wait for data to load
    WebDriverWait(browser, 60).until(EC.presence_of_all_elements_located((By.XPATH, "//a[@class='exportData']")))

    # download data
    if dt:
        url = f'https://dailyfantasynerd.com/optimizer/draftkings/nba?d={dt.strftime("%a %b %d %Y")}'
    else:
        url = 'https://dailyfantasynerd.com/optimizer/draftkings/nba'

    browser.get(url)
    WebDriverWait(browser, 60).until(EC.presence_of_all_elements_located((By.XPATH, "//a[@class='exportData']")))
    browser.find_element_by_xpath("//a[@class='exportData']").click()

    # load to pandas
    data_element = browser.find_element_by_xpath("//a[@download]")
    os.remove(os.path.join('/tmp', data_element.get_attribute('download').replace('/', '_')))

    data = data_element.get_attribute('href')
    data = urllib.parse.unquote(data[data.find('Player%20Name'):])

    df = pd.read_csv(io.StringIO(data))
    df.columns = [re.sub('\W', '_', c).lower() for c in df.columns]
    df = df[df.columns[~df.columns.str.contains("^actual_.+", regex=True)]]

    out = f"gs://djr-data/dfs-data/dfn/projections_{'test' if test else dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        df.to_csv(f, index=False)

    return out


def rotoguru_scrape(dt=None, test=False):
    """
    Download actual FP scored from RotoGurus
    """
    dt = dt or get_current_dt()

    # get data
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}
    url = f'http://rotoguru1.com/cgi-bin/hyday.pl?mon={dt.month}&day={dt.day}&year={dt.year}&game=dk&scsv=1'
    response = requests.get(url, headers=headers)
    html = BeautifulSoup(response.text, features="lxml")
    table = str(html.find("pre").text)

    # convert to pandas
    df = pd.read_csv(io.StringIO(table), sep=';')
    df.columns = [re.sub('\W', '_', c).lower() for c in df.columns]
    if len(df) == 0:
        return

    # process and format
    def get_stat(x, regex):
        try:
            return int(re.compile(regex).search(x).group(1))
        except AttributeError:
            return 0

    def process_name(x):
        last, first = x.split(', ')
        return f'{first} {last}'

    df = (
        df
        .assign(
            name=lambda x: x.name.apply(process_name),
            team=lambda x: x.team.str.upper(),
            oppt=lambda x: x.team.str.upper(),
            dnp=lambda x: x.minutes.astype(str).fillna('').str.contains('DNP').astype(int),
            minutes=lambda x: x.minutes.astype(str).replace('DNP', 0).astype(float),
            starter=lambda x: x.starter.fillna(0).astype(int),
            points=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)pt'),
            rebounds=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)rb'),
            assists=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)as'),
            steals=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)st'),
            treys=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)trey'),
            blocks=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)bl'),
            turnovers=lambda x: x['stat_line'].fillna('').apply(get_stat, regex='([0-9]+)to'),
            double_double=lambda x: ((x[['points', 'rebounds', 'assists', 'blocks', 'steals']] >= 10).astype(int).sum(axis=1) >= 2).astype(int),
            triple_double=lambda x: ((x[['points', 'rebounds', 'assists', 'blocks', 'steals']] >= 10).astype(int).sum(axis=1) >= 3).astype(int),
            dk_pts_qc=lambda x: x.points*1 + x.treys*0.5 + x.rebounds*1.25 + x.assists*1.5 + x.steals*2 + x.blocks*2 - x.turnovers*0.5 + x.double_double*1.5 + x.triple_double*3
        )
    )

    if not df.dk_salary.isnull().all():
        df = df.assign(dk_salary=lambda x: x['dk_salary'].str.replace(',', '').str.replace('$', '').astype(float))

    out = f"gs://djr-data/dfs-data/rotoguru/actuals_{'test' if test else dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        df.to_csv(f, index=False)

    return out


@app.route("/projections")
def projections():

    dt = get_current_dt()
    rotowire_scrape_out = rotowire_scrape(dt)
    numberfire_scrape_out = numberfire_scrape(dt)
    dfn_scrape_out = dfn_scrape(dt)

    return f"""
    Downloaded RotoWire data to {rotowire_scrape_out}...
    Downloaded NumberFire data to {numberfire_scrape_out}...
    Downloaded DFN data to {dfn_scrape_out}...
    Done.
    """


@app.route("/actuals")
def actuals():

    if request.args.get('dt'):
        dt = datetime.datetime.strptime("%Y%m%d")
    else:
        dt = get_current_dt() - datetime.timedelta(days=1)

    rotoguru_scrape_out = rotoguru_scrape(dt)

    return f"""
    Downloaded RotoGuru data to {rotoguru_scrape_out}...
    Done.
    """


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
