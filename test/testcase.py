# Copyright (c) 2012, the Dart project authors.  Please see the AUTHORS file
# for details. All rights reserved. Use of this source code is governed by a
# BSD-style license that can be found in the LICENSE file.

import base64
import unittest
from StringIO import StringIO

import cherrypy
import webtest
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto import Random
from google.appengine.ext import deferred
from google.appengine.ext.testbed import Testbed, TASKQUEUE_SERVICE_NAME
from google.appengine.api import users
import yaml
import tarfile

from pub_dartlang import Application
from models.package_version import PackageVersion
from models.private_key import PrivateKey
from models.pubspec import Pubspec

class TestCase(unittest.TestCase):
    """Utility methods for testing.

    This class should be used as the superclass of all other test classes. It
    sets up the necessary test stubs and provides various utility methods to use
    in tests.
    """

    def setUp(self):
        """Initialize stubs for testing.

        This initializes the following fields:
          self.testbed: An App Engine Testbed used for mocking App Engine
            services. This is activated, and any necessary stubs are
            initialized.
          self.testapp: A webtest.TestApp wrapping the CherryPy application.

        Subclasses that define their own setUp method should be sure to call
        this one as well.
        """

        self.__users = {}
        self.__admins = {}

        self.testbed = Testbed()
        self.testbed.activate()
        self.testbed.init_app_identity_stub()
        self.testbed.init_blobstore_stub()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_files_stub()
        self.testbed.init_taskqueue_stub()
        self.testbed.init_user_stub()

        self.testapp = webtest.TestApp(Application())

        # This private key is not actually used for anything other than testing.
        PrivateKey.set('''-----BEGIN RSA PRIVATE KEY-----
Proc-Type: 4,ENCRYPTED
DEK-Info: DES-EDE3-CBC,CEB8C6541017AC8B

q1SgqAfgHXK5cQvtdIF8rkSlbAS6a92T5tYMVKJIW24giF5cw+1++X7X6S5ECykC
/iECExP7WfVlPDVoJMZpWGsYLMPhxncnKfUDICbVgwsO4KKeEv8lYTrvkY1sCZIx
kSja/lGAWpyxBnmxwoLh0LbLJBGUxUgn2Uqv/8Iid+w0m3NlgrllV+kOo4gUYF9q
bestH4nEQj6F0CeI8VPW0FxzMwn0vreHFBT5hul6xbNdB1vnRcz6ed4FiGXoAB5K
/8/Q2qyy1UPe2Hr9IoC6wo4h2kXq7pmhy/rtzU9/gjsGPD33ByavbgHAen0ajY5p
RmCx0AGidK9T6/SNoyDD9CMq7ypL+0JWoCeVoAEw2aZqN4rMJNbKMgPH+ajgiAXe
AWuMVjWN6uTL5+QJmWQct6a6TF8GPKdTcOZfNIXU5U9drHB2hggLcy6XkCYGjVJv
MvLascE4oAtOHnwz7WhrpcmX6F6Fww+TPnFzjk+IGJrnBUnAArEcM13IjiDUgg9B
iLuKimwrqasdBBY3Ua3SRMoG8PJoNKdsk1hDGlpxLnqOVUCvPKZuz4QnFusnUJrR
kiv+aqVBpZYymMh2Q1MWcogA7rL7LIowAkyLzS8dNwDhyk9jbO+1uoFSHKr5BTNv
cMJfCVm8pqhXwCVx3uYnhUzvth7mcEseXh5Dcg1RHka5rCXUz4eVxTkj1u3FOy9o
9jgARPpnDYsXH1lESxmiNZucHa50qI/ezNvQx8CbNa1/+JWoZ77yqM9qnDlXUwDY
1Sxqx9+4kthG9oyCzzUwFvhf1kTEHd0RfIapgjJ16HBQmzLnEPtjPA==
-----END RSA PRIVATE KEY-----''')

    def tearDown(self):
        """Deactivates the stubs initialized in setUp.

        Subclasses that define their own tearDown method should be sure to call
        this one as well.
        """
        self.testbed.deactivate()

    def normal_user(self, name = None):
        """Constructs a non-admin user object.

        Arguments:
          name: A string to distinguish this user from others. Users with
            different names will be distinct, and the same name will always
            refer to the same user. Admin users have a separate namespace from
            non-admin users.

        Returns: The user object.
        """

        if self.__users.has_key(name):
            return self.__users[name]

        email = 'test-user@example.com'
        if name:
            email = 'test-user-%s@example.com' % name

        self.__users[name] = users.User(email = email)
        return self.__users[name]

    def admin_user(self, name = None):
        """Constructs an admin user object.

        Arguments:
          name: A string to distinguish this user from others. Users with
            different names will be distinct, and the same name will always
            refer to the same user. Admin users have a separate namespace from
            non-admin users.

        Returns: The user object.
        """

        if self.__admins.has_key(name):
            return self.__admins[name]

        email = 'test-admin@example.com'
        if name:
            email = 'test-admin-%s@example.com' % name

        self.__admins[name] = users.User(email = email)
        return self.__admins[name]

    def be_normal_user(self, name = None):
        """Log in as a non-admin user.

        Arguments:
          name: A string to distinguish this user from others. Users with
            different names will be distinct, and the same name will always
            refer to the same user. Admin users have a separate namespace from
            non-admin users.
        """
        self.testbed.setup_env(
            user_email = self.normal_user(name).email(),
            overwrite = True)

    def be_admin_user(self, name = None):
        """Log in as an admin user.

        Arguments:
          name: A string to distinguish this user from others. Users with
            different names will be distinct, and the same name will always
            refer to the same user. Admin users have a separate namespace from
            non-admin users.
        """
        self.testbed.setup_env(
            user_email = self.admin_user(name).email(),
            user_is_admin = '1',
            overwrite = True)

    def package_version(self, package, version,
                       **additional_pubspec_fields):
        """Create a package version object.

        This constructs the package archive based on the other information
        passed in. The archive contains only the pubspec.
        """
        pubspec = Pubspec(name=package.name, version=version)
        pubspec.update(additional_pubspec_fields)
        return PackageVersion.new(
            version=version,
            package=package,
            pubspec=pubspec,
            contents=self.tar_pubspec(pubspec))

    def tar_pubspec(self, pubspec):
        """Return a tarfile containing the given pubspec.

        The pubspec is dumped to YAML, then placed in a tarfile. The tarfile is
        then returned as a string.
        """
        tarfile_io = StringIO()
        tar = tarfile.open(fileobj=tarfile_io, mode='w:gz')

        tarinfo = tarfile.TarInfo("pubspec.yaml")
        pubspec_io = StringIO(yaml.dump(pubspec))
        tarinfo.size = len(pubspec_io.getvalue())
        tar.addfile(tarinfo, pubspec_io)
        tar.close()

        return tarfile_io.getvalue()

    def upload_archive(self, name, version, **additional_pubspec_fields):
        """Return a tuple representing a package archive upload."""
        pubspec = {'name': name, 'version': version}
        pubspec.update(additional_pubspec_fields)
        contents = self.tar_pubspec(pubspec)
        return ('file', '%s-%s.tar.gz' % (name, version), contents)

    def assert_requires_login(self, response):
        """Assert that the given response is requesting user authentication."""
        self.assertEqual(response.status_int, 302)
        self.assertTrue(
            response.headers['Location'].startswith(
                'https://www.google.com/accounts/Login?continue='),
            'expected response to redirect to the Google login page')

    def assert_error_page(self, response):
        """Assert that the given response renders an HTTP error page.

        This only checks for HTTP errors; it will not detect flash error
        messages.

        Arguments:
          response: The webtest response object to check.
        """
        # TODO(nweiz): Make a better error page that's easier to detect
        error_pre = self.html(response).find('pre', id='traceback')
        self.assertTrue(error_pre is not None, "expected error page")

    def html(self, response):
        """Parse a webtest response with BeautifulSoup.

        WebTest includes built-in support for BeautifulSoup 3.x, but we want to
        be able to use the features in 4.x.

        Arguments:
          response: The webtest response object to parse.

        Returns: The BeautifulSoup parsed HTML.
        """
        return BeautifulSoup(response.body)

    def assert_link(self, response, url):
        """Assert that the response contains a link to the given url.

        Arguments:
          response: The webtest response object to check.
          url: The link URL to look for.
        """
        error_msg = "expected response body to contain a link to '%s'" % url
        self.assertTrue(self._link_exists(response, url), error_msg)

    def assert_no_link(self, response, url):
        """Assert that the response doesn't contain a link to the given url.

        Arguments:
          response: The webtest response object to check.
          url: The link URL to look for.
        """
        error_msg = "expected response body not to contain a link to '%s'" % url
        self.assertFalse(self._link_exists(response, url), error_msg)

    def run_deferred_tasks(self, queue='default'):
        """Run all tasks that have been deferred.

        Arguments:
          queue: The task queue in which the deferred tasks are queued.
        """
        taskqueue_stub = self.testbed.get_stub(TASKQUEUE_SERVICE_NAME)
        for task in taskqueue_stub.GetTasks(queue):
            deferred.run(base64.b64decode(task['body']))

    def _link_exists(self, response, url):
        """Return whether or not the response contains a link to the given url.

        Arguments:
          response: The webtest response object to check.
          url: The link URL to look for.
        """

        return any([link['href'] == url for link
                    in self.html(response).find_all('a')])
