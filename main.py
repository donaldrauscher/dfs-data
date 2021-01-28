import datetime, json, os, re

import requests
import pandas as pd
from gcsfs import GCSFileSystem
from flask import Flask


app = Flask(__name__)


def rotowire_scrape():
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

    out = f"gs://djr-data/dfs-data/projections_{datetime.date.today().strftime('%Y%m%d')}.csv"

    fs = GCSFileSystem(project='blog-180218')
    with fs.open(out, "w") as f:
        players.to_csv(f, index=False)

    return out


@app.route("/")
def index():
    rw_scrape_out = rotowire_scrape()
    return f"""
    Downloaded RotoWire data to {rw_scrape_out}...
    Done.
    """


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
