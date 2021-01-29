import datetime
import click
import main


@click.group()
def cli():
    pass


@cli.command()
def rotowire_scrape():
    print(main.rotowire_scrape(test=True))


@cli.command()
def numberfire_scrape():
    print(main.numberfire_scrape(test=True))


@cli.command()
@click.option('--dt', type=str)
def rotoguru_scrape(dt):
    if dt:
        dt = datetime.datetime.strptime("%Y%m%d")
    else:
        dt = main.get_current_dt() - datetime.timedelta(days=1)
    print(main.rotoguru_scrape(dt, test=True))


if __name__ == "__main__":
    cli(obj={})
