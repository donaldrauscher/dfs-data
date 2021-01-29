import datetime, io, json, os, re, pytz, warnings

import requests
import pandas as pd
from bs4 import BeautifulSoup

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
    df.columns = [re.sub('\W', '_', c) for c in df.columns]
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
            Name=lambda x: x.Name.apply(process_name),
            Team=lambda x: x.Team.str.upper(),
            Oppt=lambda x: x.Team.str.upper(),
            DNP=lambda x: x.Minutes.astype(str).fillna('').str.contains('DNP').astype(int),
            Minutes=lambda x: x.Minutes.astype(str).replace('DNP', 0).astype(float),
            Starter=lambda x: x.Starter.fillna(0).astype(int),
            Points=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)pt'),
            Rebounds=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)rb'),
            Assists=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)as'),
            Steals=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)st'),
            Treys=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)trey'),
            Blocks=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)bl'),
            Turnovers=lambda x: x['Stat_line'].fillna('').apply(get_stat, regex='([0-9]+)to'),
            Double_Double=lambda x: ((x[['Points', 'Rebounds', 'Assists', 'Blocks', 'Steals']] >= 10).astype(int).sum(axis=1) >= 2).astype(int),
            Triple_Double=lambda x: ((x[['Points', 'Rebounds', 'Assists', 'Blocks', 'Steals']] >= 10).astype(int).sum(axis=1) >= 3).astype(int),
            DK_Pts_QC=lambda x: x.Points*1 + x.Treys*0.5 + x.Rebounds*1.25 + x.Assists*1.5 + x.Steals*2 + x.Blocks*2 - x.Turnovers*0.5 + x.Double_Double*1.5 + x.Triple_Double*3
        )
    )

    if not df.DK_Salary.isnull().all():
        df = df.assign(DK_Salary=lambda x: x['DK_Salary'].str.replace(',', '').str.replace('$', '').astype(float))

    df.columns = [c.lower() for c in df.columns]

    out = f"gs://djr-data/dfs-data/rotoguru/actuals_{'test' if test else dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        df.to_csv(f, index=False)

    return out


@app.route("/projections")
def projections():

    dt = get_current_dt()
    rotowire_scrape_out = rotowire_scrape(dt)
    numberfire_scrape_out = numberfire_scrape(dt)

    return f"""
    Downloaded RotoWire data to {rotowire_scrape_out}...
    Downloaded NumberFire data to {numberfire_scrape_out}...
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
