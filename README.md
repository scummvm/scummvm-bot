# Commitbot

Commitbot is an IRC bot with a Github webhook server based on the Twisted framework.
It is loosely inspired by [gitbot](https://github.com/thedjinn/gitbot).

Features
========

Commitbot supports the following features:

* Github webhook with secret
* IRC over TLS (using a custom CA)
* Multiple channel over the server (only one server supported)
* Filtering of notifications by channel and repository

Installation
============

You can install Commitbot from a local clone of this repository by running:

     pip install .[tls]

Usage
=====

* Copy config.ini.example to config.ini
* Edit the settings to match your setup
* Setup a webhook on your Github project. Use the following url: `http://<yourhost>:5651/github` and the secret you specified in the configuration.
* Run the bot with the command `commitbot` in your Python environment.
* Do you usual stuff on your project and see the notifications flying in your IRC channels.

Development
===========

Linting is done using ruff and mypy.
They can be installed by running:

    pip install --group=lint -e .
