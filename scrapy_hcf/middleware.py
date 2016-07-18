import os
import hashlib
import logging
from collections import defaultdict
from datetime import datetime
from scrapinghub import Connection
from scrapy import signals, log
from scrapy.exceptions import NotConfigured
from scrapy.http import Request
from hubstorage import HubstorageClient

DEFAULT_MAX_LINKS = 1000
DEFAULT_HS_NUMBER_OF_SLOTS = 8


class HcfMiddleware(object):

    def __init__(self, crawler):
        settings = crawler.settings
        self.hs_endpoint = settings.get("HS_ENDPOINT")
        self.hs_auth = self._get_config(settings, "HS_AUTH")
        self.hs_projectid = self._get_config(settings, "HS_PROJECTID", os.environ.get('SCRAPY_PROJECT_ID'))
        self.hs_frontier = self._get_config(settings, "HS_FRONTIER")
        self.hs_consume_from_slot = self._get_config(settings, "HS_CONSUME_FROM_SLOT")
        self.hs_number_of_slots = settings.getint("HS_NUMBER_OF_SLOTS", DEFAULT_HS_NUMBER_OF_SLOTS)
        self.hs_max_links = settings.getint("HS_MAX_LINKS", DEFAULT_MAX_LINKS)
        self.hs_start_job_enabled = settings.getbool("HS_START_JOB_ENABLED", False)
        self.hs_start_job_on_reason = settings.getlist("HS_START_JOB_ON_REASON", ['finished'])

        conn = Connection(self.hs_auth)
        self.panel_project = conn[self.hs_projectid]

        self.hsclient = HubstorageClient(auth=self.hs_auth, endpoint=self.hs_endpoint)
        self.project = self.hsclient.get_project(self.hs_projectid)
        self.fclient = self.project.frontier

        self.new_links = defaultdict(set)
        self.batch_ids = []

        crawler.signals.connect(self.close_spider, signals.spider_closed)

        # Make sure the logger for hubstorage.batchuploader is configured
        logging.basicConfig()

    def _get_config(self, settings, key, default=None):
        value = settings.get(key, default)
        if not value:
            raise NotConfigured('%s not found' % key)
        return value

    def _msg(self, msg, level=log.INFO):
        log.msg('(HCF) %s' % msg, level)

    def start_job(self, spider):
        self._msg("Starting new job for: %s" % spider.name)
        jobid = self.panel_project.schedule(
            spider.name,
            hs_consume_from_slot=self.hs_consume_from_slot,
            dummy=datetime.now()
        )
        self._msg("New job started: %s" % jobid)
        return jobid

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_start_requests(self, start_requests, spider):

        self.hs_frontier = getattr(spider, 'hs_frontier', self.hs_frontier)
        self._msg('Using HS_FRONTIER=%s' % self.hs_frontier)

        self.hs_consume_from_slot = getattr(spider, 'hs_consume_from_slot', self.hs_consume_from_slot)
        self._msg('Using HS_CONSUME_FROM_SLOT=%s' % self.hs_consume_from_slot)

        self.has_new_requests = False
        for req in self._get_new_requests():
            self.has_new_requests = True
            yield req

        # if there are no links in the hcf, use the start_requests
        # unless this is not the first job.
        if not self.has_new_requests and not getattr(spider, 'dummy', None):
            self._msg('Using start_requests')
            for r in start_requests:
                yield r

    def process_spider_output(self, response, result, spider):
        slot_callback = getattr(spider, 'slot_callback', self._get_slot)
        for item in result:
            if isinstance(item, Request):
                request = item
                if request.meta.get('use_hcf', False):
                    if request.method == 'GET':  # XXX: Only GET support for now.
                        slot = slot_callback(request)
                        if not request.url in self.new_links[slot]:
                            hcf_params = request.meta.get('hcf_params')
                            fp = {'fp': request.url}
                            if hcf_params:
                                fp.update(hcf_params)
                            # Save the new links as soon as possible using
                            # the batch uploader
                            self.fclient.add(self.hs_frontier, slot, [fp])
                            self.new_links[slot].add(request.url)
                    else:
                        self._msg("'use_hcf' meta key is not supported for non GET requests (%s)" % request.url,
                                  log.ERROR)
                        yield request
                else:
                    yield request
            else:
                yield item

    def close_spider(self, spider, reason):
        # Only store the results if the spider finished normally, if it
        # didn't finished properly there is not way to know whether all the url batches
        # were processed and it is better not to delete them from the frontier
        # (so they will be picked by another process).
        if reason == 'finished':
            self._save_new_links_count()
            self._delete_processed_ids()

        # Close the frontier client in order to make sure that all the new links
        # are stored.
        self.fclient.close()
        self.hsclient.close()

        # If the reason is defined in the hs_start_job_on_reason list then start
        # a new job right after this spider is finished.
        if self.hs_start_job_enabled and reason in self.hs_start_job_on_reason:

            # Start the new job if this job had requests from the HCF or it
            # was the first job.
            if self.has_new_requests or not getattr(spider, 'dummy', None):
                self.start_job(spider)

    def _get_new_requests(self):
        """ Get a new batch of links from the HCF."""
        num_batches = 0
        num_links = 0
        for num_batches, batch in enumerate(self.fclient.read(self.hs_frontier, self.hs_consume_from_slot), 1):
            for fingerprint, data in batch['requests']:
                num_links += 1
                yield Request(url=fingerprint, meta={'hcf_params': {'qdata': data}})
            self.batch_ids.append(batch['id'])
            if num_links >= self.hs_max_links:
                break
        self._msg('Read %d new batches from slot(%s)' % (num_batches, self.hs_consume_from_slot))
        self._msg('Read %d new links from slot(%s)' % (num_links, self.hs_consume_from_slot))

    def _save_new_links_count(self):
        """ Save the new extracted links into the HCF."""
        for slot, new_links in self.new_links.items():
            self._msg('Stored %d new links in slot(%s)' % (len(new_links), slot))
        self.new_links = defaultdict(set)

    def _delete_processed_ids(self):
        """ Delete in the HCF the ids of the processed batches."""
        self.fclient.delete(self.hs_frontier, self.hs_consume_from_slot, self.batch_ids)
        self._msg('Deleted %d processed batches in slot(%s)' % (len(self.batch_ids),
                                                                self.hs_consume_from_slot))
        self.batch_ids = []

    def _get_slot(self, request):
        """ Determine to which slot should be saved the request."""
        md5 = hashlib.md5()
        md5.update(request.url)
        digest = md5.hexdigest()
        return str(int(digest, 16) % self.hs_number_of_slots)
