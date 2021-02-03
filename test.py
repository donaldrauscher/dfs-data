import datetime
import click
import main


@click.group()
@click.option('--test/--no-test', default=True)
@click.pass_context
def cli(ctx, test):
    ctx.obj['test'] = test
    ctx.ensure_object(dict)


@cli.command()
@click.pass_context
def rotowire_scrape(ctx):
    print(main.rotowire_scrape(test=ctx.obj['test']))


@cli.command()
@click.pass_context
def numberfire_scrape(ctx):
    print(main.numberfire_scrape(test=ctx.obj['test']))


@cli.command()
@click.option('--dt', type=str)
@click.pass_context
def dfn_scrape(ctx, dt):
    if dt:
        dt = datetime.datetime.strptime(dt, "%Y%m%d")
    print(main.dfn_scrape(dt=dt, test=ctx.obj['test']))


@cli.command()
@click.option('--dt', type=str)
@click.pass_context
def rotoguru_scrape(ctx, dt):
    if dt:
        dt = datetime.datetime.strptime(dt, "%Y%m%d")
    print(main.rotoguru_scrape(dt, test=ctx.obj['test']))


if __name__ == "__main__":
    cli(obj={})
