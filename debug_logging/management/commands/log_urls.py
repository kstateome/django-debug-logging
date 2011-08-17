from __future__ import with_statement
from datetime import datetime
import sys

from django.test.client import Client
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Hit a list of urls in sequence so that the requests will be logged'
    args = "url_list [url_list ...]"
    
    option_list = BaseCommand.option_list + (
        make_option('-s', '--manual-start',
            action='store_true',
            dest='manual_start',
            help='Manually start a TestRun without actually logging any urls.'
        ),
        make_option('-e', '--manual-end',
            action='store_true',
            dest='manual_end',
            help='End a TestRun that was started manually.'
        ),
        make_option('-n', '--name',
            action='store',
            dest='name',
            metavar='NAME',
            help='Add a name to the test run.'
        ),
        make_option('-d', '--description',
            action='store',
            dest='description',
            metavar='DESC',
            help='Add a description to the test run.'
        ),
        make_option('-u', '--username',
            action='store',
            dest='username',
            metavar='USERNAME',
            help='Run the test authenticated with the USERNAME provided.'
        ),
        make_option('-p', '--password',
            action='store',
            dest='password',
            metavar='PASSWORD',
            help='Run the test authenticated with the PASSWORD provided.'
        ),
    )
    
    def status_update(self, msg):
        if not self.quiet:
            print msg
    
    def status_ticker(self):
        if not self.quiet:
            sys.stdout.write('.')
            sys.stdout.flush()
    
    def handle(self, *url_lists, **options):
        from django.conf import settings
        from debug_logging.models import TestRun
        from debug_logging.utils import (get_project_name, get_hostname,
                                         get_revision)
        
        verbosity = int(options.get('verbosity', 1))
        self.quiet = verbosity < 1
        self.verbose = verbosity > 1
        
        # Check for a username without a password, or vice versa
        if options['username'] and not options['password']:
            raise CommandError('If a username is provided, a password must '
                               'also be provided.')
        if options['password'] and not options['username']:
            raise CommandError('If a password is provided, a username must '
                               'also be provided.')
        
        # Create a TestRun object to track this run
        filters = {}
        panels = settings.DEBUG_TOOLBAR_PANELS
        if 'debug_logging.panels.identity.IdentityLoggingPanel' in panels:
            filters['project_name'] = get_project_name()
            filters['hostname'] = get_hostname()
        if 'debug_logging.panels.revision.RevisionLoggingPanel' in panels:
            filters['revision'] = get_revision()
        
        # Check to see if there is already a TestRun object open
        existing_run = TestRun.objects.filter(end__isnull=True, **filters)
        if existing_run:
            if options['manual_start']:
                # If the --manual-start option was specified, error out because
                # there is already an open TestRun
                raise CommandError('There is already an open TestRun.')
            
            # Otherwise, close it so that we can open a new one
            existing_run.end = datetime.now()
            existing_run.save()
            
            if options['manual_end']:
                # If the --manual-end option was specified, we can now exit
                self.status_update('The TestRun was successfully closed.')
                return
        if options['manual_end']:
            # The --manual-end option was specified, but there was no existing
            # run to close.
            raise CommandError('There is no open TestRun to end.')
        
        filters['start'] = datetime.now()
        test_run = TestRun(**filters)
        
        if options['name']:
            test_run.name = options['name']
        if options['description']:
            test_run.description = options['description']
        
        test_run.save()
        
        if options['manual_start']:
            # The TestRun was successfully created
            self.status_update('A new TestRun was successfully opened.')
            return
        
        urls = []
        for url_list in url_lists:
            with open(url_list) as f:
                urls.extend([l.strip() for l in f.readlines()
                             if not l.startswith('#')])
        
        self.status_update('Beginning debug logging run...')
        
        client = Client()
        
        if options['username'] and options['password']:
            client.login(username=options['username'],
                         password=options['password'])
        
        for url in urls:
            try:
                response = client.get(url)
            except KeyboardInterrupt, e:
                # Close out the log entry
                test_run.end = datetime.now()
                test_run.save()
                
                raise CommandError('Debug logging run cancelled.')
            except:
                if self.verbose:
                    self.status_update('\nSkipped %s because of an error'
                                       % url)
                    continue
            if response and response.status_code == 200:
                self.status_ticker()
            else:
                self.status_update('\nURL %s responded with code %s'
                                   % (url, response.status_code))
        
        # Close out the log entry
        test_run.end = datetime.now()
        test_run.save()
        
        self.status_update('done!\n')
