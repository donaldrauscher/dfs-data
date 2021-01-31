## dfs-data

Download DFS data from RW, DK, etc. into my GCS bucket periodically.  Deployed as Cloud Run service that is invoked with Cloud Scheduler.


Test image:
```
docker run --rm -p 9090:8080 -e PORT=8080 \
  -e DFN_USER=$DFN_USER \
  -e DFN_PASS=$DFN_PASS \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/keys/blog-180218-djr-test-sa.json \
  -v $GOOGLE_APPLICATION_CREDENTIALS:/tmp/keys/blog-180218-djr-test-sa.json:ro \
  gcr.io/blog-180218/dfs-data:latest
```

Resources: 
- [https://cloud.google.com/run/docs/triggering/using-scheduler](https://cloud.google.com/run/docs/triggering/using-scheduler)
- [https://github.com/kevinhowbrook/Selenium-Python-Docker-scraper](https://github.com/kevinhowbrook/Selenium-Python-Docker-scraper)