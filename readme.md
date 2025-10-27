## THSR-Bot

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

TBD

## Deploying on Render

Region: Singapore
Build Command: pip install -r requirements_thsr_bot.txt --ignore-requires-python
Start Command: gunicorn app:app
Instance Type: Free (** Important **)

Auto-Deploy: Off

## Appendix

We may use Microsoft teams webhook to trigger an thsr-inquiry immediately

```
<Teams @ Home> -- <Teams @ Office> -- <Python@Office> -- inquiry -- <Flask-THSR>
```
