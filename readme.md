# THSR-Bot

Use [Flask](http://flask.pocoo.org/) to parse HTTP POST messages from websites or line-bot (webhook) and process them.

Keywords: [Flask](http://flask.pocoo.org/), [Flask Source](https://github.com/pallets/flask)

## Getting started

```
$ export LINE_CHANNEL_SECRET=YOUR_LINE_CHANNEL_SECRET
$ export LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN

$ pip install -r requirements.txt --ignore-requires-python
```

Run Flask application - flask-thsr

```
$ python app.py
```

## Running on GitHub Codespace

### Installing Python dependencies
```
python -m venv venv
source ./venv/bin/activate
pip install --upgrade pip
pip install -r requirements_thsr_bot.txt --ignore-requires-python
```

### Run Gunicorn
```
(venv) /workspaces/projects/thsr-bot/ $ gunicorn --env DEPLOY_ENV=Render app:app
[2025-10-28 19:37:45 +0800] [24332] [INFO] Starting gunicorn 23.0.0
[2025-10-28 19:37:45 +0800] [24332] [INFO] Listening at: http://127.0.0.1:8000 (24332)
[2025-10-28 19:37:45 +0800] [24332] [INFO] Using worker: sync
[2025-10-28 19:37:45 +0800] [24336] [INFO] Booting worker with pid: 24336
```


## Deploying on Render

Region: Singapore
Build Command: pip install -r requirements_thsr_bot.txt --ignore-requires-python
Start Command: gunicorn --bind 0.0.0.0:8000 app:app
Instance Type: Free (** Important **)

Auto-Deploy: Off

## Appendix

We may use Microsoft teams webhook to trigger an thsr-inquiry immediately

```
<Teams @ Home> -- <Teams @ Office> -- <Python@Office> -- inquiry -- <Flask-THSR>
```
