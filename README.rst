==========
scrapy-hcf
==========

.. image:: https://travis-ci.org/scrapy-plugins/scrapy-hcf.svg?branch=master
    :target: https://travis-ci.org/scrapy-plugins/scrapy-hcf

.. image:: https://codecov.io/gh/scrapy-plugins/scrapy-hcf/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/scrapy-plugins/scrapy-hcf


This Scrapy spider middleware uses the HCF backend from Scrapinghub's
Scrapy Cloud service to retrieve the new urls to crawl
and store back the links extracted.


Installation
============

Install scrapy-hcf using ``pip``::

    $ pip install scrapy-hcf


Configuration
=============

To activate this middleware it needs to be added to the ``SPIDER_MIDDLEWARES``
dict, i.e::

    SPIDER_MIDDLEWARES = {
        'scrapy_hcf.HcfMiddleware': 543,
    }

And the following settings need to be defined:

``HS_AUTH``
    Scrapy Cloud API key

``HS_PROJECTID``
    Scrapy Cloud project ID (not needed if the spider is ran on dash)

``HS_FRONTIER``
    Frontier name.

``HS_CONSUME_FROM_SLOT``
    Slot from where the spider will read new URLs.

Note that ``HS_FRONTIER`` and ``HS_CONSUME_FROM_SLOT`` can be overriden
from inside a spider using the spider attributes ``hs_frontier``
and ``hs_consume_from_slot`` respectively.

The following optional Scrapy settings can be defined:

``HS_ENDPOINT``
    URL to the API endpoint, i.e: http://localhost:8003.
    The default value is provided by the python-hubstorage package.

``HS_MAX_LINKS``
    Number of links to be read from the HCF, the default is 1000.

``HS_START_JOB_ENABLED``
    Enable whether to start a new job when the spider finishes.
    The default is ``False``

``HS_START_JOB_ON_REASON``
    This is a list of closing reasons,
    if the spider ends with any of these reasons a new job will be started
    for the same slot. The default is ``['finished']``

``HS_NUMBER_OF_SLOTS``
    This is the number of slots that the middleware will use to store the new links.
    The default is 8.


Usage
=====

The following keys can be defined in a Scrapy Request meta in order to control the behavior
of the HCF middleware:

``'use_hcf'``
    If set to ``True`` the request will be stored in the HCF.

``'hcf_params'``
    Dictionary of parameters to be stored in the HCF with the request fingerprint

    ``'qdata'``
        data to be stored along with the fingerprint in the request queue

    ``'fdata'``
        data to be stored along with the fingerprint in the fingerprint set

    ``'p'``
        Priority - lower priority numbers are returned first. The default is 0

The value of ``'qdata'`` parameter could be retrieved later using
``response.meta['hcf_params']['qdata']``.

The spider can override the default slot assignation function by setting the
spider ``slot_callback`` method to a function with the following signature::

       def slot_callback(request):
           ...
           return slot
