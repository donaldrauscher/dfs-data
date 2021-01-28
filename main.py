import datetime, json, os, re, pytz

import requests
import lxml.html as LH
from bs4 import BeautifulSoup

import pandas as pd

from gcsfs import GCSFileSystem
from flask import Flask


app = Flask(__name__)
fs = GCSFileSystem(project='blog-180218')


def rotowire_scrape(dt):
    """
    Download RotoWire player projections
    """
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
        .filter(['rw_id', 'player', 'team', 'opponent', 'is_home', 'salary', 'injury_status',
                 'ownership', 'proj_avg', 'proj_site', 'proj_rotowire', 'proj_ceiling'])
    )

    out = f"gs://djr-data/dfs-data/rotowire/projections_{dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        players.to_csv(f, index=False)

    return out


def numberfire_scrape(dt):
    """
    Download NumberFire player projections
    """
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

    out = f"gs://djr-data/dfs-data/numberfire/projections_{dt.strftime('%Y%m%d')}.csv"
    with fs.open(out, "w") as f:
        players.to_csv(f, index=False)

    return out


@app.route("/")
def index():
    dt = pytz.utc.localize(datetime.datetime.utcnow(), is_dst=None).astimezone(pytz.timezone('America/Chicago'))

    rotowire_scrape_out = rotowire_scrape(dt)
    numberfire_scrape_out = numberfire_scrape(dt)

    return f"""
    Downloaded RotoWire data to {rotowire_scrape_out}...
    Downloaded NumberFire data to {numberfire_scrape_out}...
    Done.
    """


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
