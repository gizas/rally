# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# 	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import asyncio
import contextlib
import logging
import os
import random
import ssl
from copy import deepcopy
from unittest import mock

import elasticsearch
import pytest
import trustme
import urllib3.exceptions
from pytest_httpserver import HTTPServer

from esrally import client, doc_link, exceptions
from esrally.client.asynchronous import AIOHttpConnection
from esrally.utils import console


class TestEsClientFactory:
    cwd = os.path.dirname(__file__)

    def test_create_http_connection(self):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {}
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = dict(client_options)

        f = client.EsClientFactory(hosts, client_options)

        assert f.hosts == hosts
        assert f.ssl_context is None
        assert f.client_options["scheme"] == "http"
        assert "http_auth" not in f.client_options

        assert client_options == original_client_options

    @mock.patch.object(ssl.SSLContext, "load_cert_chain")
    def test_create_https_connection_verify_server(self, mocked_load_cert_chain):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
        }
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = deepcopy(client_options)

        logger = logging.getLogger("esrally.client.factory")
        with mock.patch.object(logger, "info") as mocked_info_logger:
            f = client.EsClientFactory(hosts, client_options)
        mocked_info_logger.assert_has_calls(
            [
                mock.call("SSL support: on"),
                mock.call("SSL certificate verification: on"),
                mock.call("SSL client authentication: off"),
            ]
        )

        assert (
            not mocked_load_cert_chain.called
        ), "ssl_context.load_cert_chain should not have been called as we have not supplied client certs"

        assert f.hosts == hosts
        assert f.ssl_context.check_hostname
        assert f.ssl_context.verify_mode == ssl.CERT_REQUIRED

        assert f.client_options["scheme"] == "https"
        assert f.client_options["http_auth"] == ("user", "password")
        assert "use_ssl" not in f.client_options
        assert "verify_certs" not in f.client_options
        assert "ca_certs" not in f.client_options

        assert client_options == original_client_options

    @mock.patch.object(ssl.SSLContext, "load_cert_chain")
    def test_create_https_connection_verify_self_signed_server_and_client_certificate(self, mocked_load_cert_chain):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
            "ca_certs": os.path.join(self.cwd, "../utils/resources/certs/ca.crt"),
            "client_cert": os.path.join(self.cwd, "../utils/resources/certs/client.crt"),
            "client_key": os.path.join(self.cwd, "../utils/resources/certs/client.key"),
        }
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = deepcopy(client_options)

        logger = logging.getLogger("esrally.client.factory")
        with mock.patch.object(logger, "info") as mocked_info_logger:
            f = client.EsClientFactory(hosts, client_options)
        mocked_info_logger.assert_has_calls(
            [
                mock.call("SSL support: on"),
                mock.call("SSL certificate verification: on"),
                mock.call("SSL client authentication: on"),
            ]
        )

        mocked_load_cert_chain.assert_called_with(
            certfile=client_options["client_cert"],
            keyfile=client_options["client_key"],
        )

        assert f.hosts == hosts
        assert f.ssl_context.check_hostname
        assert f.ssl_context.verify_mode == ssl.CERT_REQUIRED

        assert f.client_options["scheme"] == "https"
        assert f.client_options["http_auth"] == ("user", "password")
        assert "use_ssl" not in f.client_options
        assert "verify_certs" not in f.client_options
        assert "ca_certs" not in f.client_options
        assert "client_cert" not in f.client_options
        assert "client_key" not in f.client_options

        assert client_options == original_client_options

    @mock.patch.object(ssl.SSLContext, "load_cert_chain")
    def test_create_https_connection_only_verify_self_signed_server_certificate(self, mocked_load_cert_chain):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
            "ca_certs": os.path.join(self.cwd, "../utils/resources/certs/ca.crt"),
        }
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = deepcopy(client_options)

        logger = logging.getLogger("esrally.client.factory")
        with mock.patch.object(logger, "info") as mocked_info_logger:
            f = client.EsClientFactory(hosts, client_options)
        mocked_info_logger.assert_has_calls(
            [
                mock.call("SSL support: on"),
                mock.call("SSL certificate verification: on"),
                mock.call("SSL client authentication: off"),
            ]
        )

        assert (
            not mocked_load_cert_chain.called
        ), "ssl_context.load_cert_chain should not have been called as we have not supplied client certs"
        assert f.hosts == hosts
        assert f.ssl_context.check_hostname
        assert f.ssl_context.verify_mode == ssl.CERT_REQUIRED

        assert f.client_options["scheme"] == "https"
        assert f.client_options["http_auth"] == ("user", "password")
        assert "use_ssl" not in f.client_options
        assert "verify_certs" not in f.client_options
        assert "ca_certs" not in f.client_options

        assert client_options == original_client_options

    def test_raises_error_when_only_one_of_client_cert_and_client_key_defined(self):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
            "ca_certs": os.path.join(self.cwd, "../utils/resources/certs/ca.crt"),
        }

        client_ssl_options = {"client_cert": "../utils/resources/certs/client.crt", "client_key": "../utils/resources/certs/client.key"}

        random_client_ssl_option = random.choice(list(client_ssl_options.keys()))
        missing_client_ssl_option = list(set(client_ssl_options) - set([random_client_ssl_option]))[0]
        client_options.update({random_client_ssl_option: client_ssl_options[random_client_ssl_option]})

        with pytest.raises(exceptions.SystemSetupError) as ctx:
            with mock.patch.object(console, "println") as mocked_console_println:
                client.EsClientFactory(hosts, client_options)
        mocked_console_println.assert_called_once_with(
            "'{}' is missing from client-options but '{}' has been specified.\n"
            "If your Elasticsearch setup requires client certificate verification both need to be supplied.\n"
            "Read the documentation at {}\n".format(
                missing_client_ssl_option,
                random_client_ssl_option,
                console.format.link(doc_link("command_line_reference.html#client-options")),
            )
        )
        assert ctx.value.args[0] == (
            "Cannot specify '{}' without also specifying '{}' in client-options.".format(
                random_client_ssl_option, missing_client_ssl_option
            )
        )

    @mock.patch.object(ssl.SSLContext, "load_cert_chain")
    def test_create_https_connection_unverified_certificate(self, mocked_load_cert_chain):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": False,
            "basic_auth_user": "user",
            "basic_auth_password": "password",
        }
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = dict(client_options)

        logger = logging.getLogger("esrally.client.factory")
        with mock.patch.object(logger, "info") as mocked_info_logger:
            f = client.EsClientFactory(hosts, client_options)
        mocked_info_logger.assert_has_calls(
            [
                mock.call("SSL support: on"),
                mock.call("SSL certificate verification: off"),
                mock.call("SSL client authentication: off"),
            ]
        )

        assert (
            not mocked_load_cert_chain.called
        ), "ssl_context.load_cert_chain should not have been called as we have not supplied client certs"

        assert f.hosts == hosts
        assert not f.ssl_context.check_hostname
        assert f.ssl_context.verify_mode == ssl.CERT_NONE

        assert f.client_options["scheme"] == "https"
        assert f.client_options["http_auth"] == ("user", "password")
        assert "use_ssl" not in f.client_options
        assert "verify_certs" not in f.client_options
        assert "basic_auth_user" not in f.client_options
        assert "basic_auth_password" not in f.client_options

        assert client_options == original_client_options

    @mock.patch.object(ssl.SSLContext, "load_cert_chain")
    def test_create_https_connection_unverified_certificate_present_client_certificates(self, mocked_load_cert_chain):
        hosts = [{"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": False,
            "http_auth": ("user", "password"),
            "client_cert": os.path.join(self.cwd, "../utils/resources/certs/client.crt"),
            "client_key": os.path.join(self.cwd, "../utils/resources/certs/client.key"),
        }
        # make a copy so we can verify later that the factory did not modify it
        original_client_options = deepcopy(client_options)

        logger = logging.getLogger("esrally.client.factory")
        with mock.patch.object(logger, "info") as mocked_info_logger:
            f = client.EsClientFactory(hosts, client_options)
        mocked_info_logger.assert_has_calls(
            [
                mock.call("SSL certificate verification: off"),
                mock.call("SSL client authentication: on"),
            ],
        )

        mocked_load_cert_chain.assert_called_with(
            certfile=client_options["client_cert"],
            keyfile=client_options["client_key"],
        )

        assert f.hosts == hosts
        assert not f.ssl_context.check_hostname
        assert f.ssl_context.verify_mode == ssl.CERT_NONE

        assert f.client_options["scheme"] == "https"
        assert f.client_options["http_auth"] == ("user", "password")
        assert "use_ssl" not in f.client_options
        assert "verify_certs" not in f.client_options
        assert "basic_auth_user" not in f.client_options
        assert "basic_auth_password" not in f.client_options
        assert "ca_certs" not in f.client_options
        assert "client_cert" not in f.client_options
        assert "client_key" not in f.client_options

        assert client_options == original_client_options

    def test_raises_error_when_verify_ssl_with_mixed_hosts(self):
        hosts = [{"host": "127.0.0.1", "port": 9200}, {"host": "localhost", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
        }

        with pytest.raises(
            exceptions.SystemSetupError,
            match="Cannot verify certs with mixed IP addresses and hostnames",
        ):
            client.EsClientFactory(hosts, client_options)

    def test_check_hostname_false_when_host_is_ip(self):
        hosts = [{"host": "127.0.0.1", "port": 9200}]
        client_options = {
            "use_ssl": True,
            "verify_certs": True,
            "http_auth": ("user", "password"),
        }

        f = client.EsClientFactory(hosts, client_options)
        assert f.hosts == hosts
        assert f.ssl_context.check_hostname is False
        assert f.ssl_context.verify_mode == ssl.CERT_REQUIRED


@contextlib.contextmanager
def _build_server(tmpdir, host):
    ca = trustme.CA()
    ca_cert_path = str(tmpdir / "ca.pem")
    ca.cert_pem.write_to_path(ca_cert_path)

    server_cert = ca.issue_cert(host)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_crt = server_cert.cert_chain_pems[0]
    server_key = server_cert.private_key_pem
    with server_crt.tempfile() as crt_file, server_key.tempfile() as key_file:
        context.load_cert_chain(crt_file, key_file)

    server = HTTPServer(ssl_context=context)
    # Fake what the client expects from Elasticsearch
    server.expect_request("/").respond_with_json(
        headers={
            "x-elastic-product": "Elasticsearch",
        },
        response_json={
            "version": {
                "number": "8.0.0",
            }
        },
    )
    server.start()

    yield server, ca, ca_cert_path

    server.clear()
    if server.is_running():
        server.stop()


class TestEsClientAgainstHTTPSServer:
    def test_ip_address(self, tmp_path_factory: pytest.TempPathFactory):
        tmpdir = tmp_path_factory.mktemp("certs")
        with _build_server(tmpdir, "127.0.0.1") as cfg:
            server, _ca, ca_cert_path = cfg
            hosts = [{"host": "127.0.0.1", "port": server.port}]
            client_options = {
                "use_ssl": True,
                "verify_certs": True,
                "ca_certs": ca_cert_path,
            }
            f = client.EsClientFactory(hosts, client_options)
            es = f.create()
            assert es.info() == {"version": {"number": "8.0.0"}}

    def test_client_cert(self, tmp_path_factory: pytest.TempPathFactory):
        tmpdir = tmp_path_factory.mktemp("certs")
        with _build_server(tmpdir, "localhost") as cfg:
            server, ca, ca_cert_path = cfg
            client_cert = ca.issue_cert("localhost")
            client_cert_path = str(tmpdir / "client.pem")
            client_key_path = str(tmpdir / "client.key")
            client_cert.cert_chain_pems[0].write_to_path(client_cert_path)
            client_cert.private_key_pem.write_to_path(client_key_path)

            hosts = [
                {"host": "localhost", "port": server.port},
            ]
            client_options = {
                "use_ssl": True,
                "verify_certs": True,
                "ca_certs": ca_cert_path,
                "client_cert": client_cert_path,
                "client_key": client_key_path,
            }
            f = client.EsClientFactory(hosts, client_options)
            es = f.create()
            assert es.info() == {"version": {"number": "8.0.0"}}


class TestRequestContextManager:
    @pytest.mark.asyncio
    async def test_propagates_nested_context(self):
        test_client = client.RequestContextHolder()
        async with test_client.new_request_context() as top_level_ctx:
            test_client.on_request_start()
            await asyncio.sleep(0.01)
            async with test_client.new_request_context() as nested_ctx:
                test_client.on_request_start()
                await asyncio.sleep(0.01)
                test_client.on_request_end()
            test_client.on_request_end()

        assert top_level_ctx.request_start < nested_ctx.request_start + 0.01
        assert top_level_ctx.request_end > nested_ctx.request_end
        assert nested_ctx.request_end > nested_ctx.request_start + 0.01


class TestRestLayer:
    @mock.patch("elasticsearch.Elasticsearch")
    def test_successfully_waits_for_rest_layer(self, es):
        es.transport.hosts = [
            {"host": "node-a.example.org", "port": 9200},
            {"host": "node-b.example.org", "port": 9200},
        ]
        assert client.wait_for_rest_layer(es, max_attempts=3)
        es.cluster.health.assert_has_calls(
            [
                mock.call(wait_for_nodes=">=2"),
            ]
        )

    # don't sleep in realtime
    @mock.patch("time.sleep")
    @mock.patch("elasticsearch.Elasticsearch")
    def test_retries_on_transport_errors(self, es, sleep):
        es.cluster.health.side_effect = [
            elasticsearch.TransportError(503, "Service Unavailable"),
            elasticsearch.TransportError(401, "Unauthorized"),
            elasticsearch.TransportError(408, "Timed Out"),
            elasticsearch.TransportError(408, "Timed Out"),
            {"version": {"number": "5.0.0", "build_hash": "abc123"}},
        ]
        assert client.wait_for_rest_layer(es, max_attempts=5)

    # don't sleep in realtime
    @mock.patch("time.sleep")
    @mock.patch("elasticsearch.Elasticsearch")
    def test_dont_retry_eternally_on_transport_errors(self, es, sleep):
        es.cluster.health.side_effect = elasticsearch.TransportError(401, "Unauthorized")
        assert not client.wait_for_rest_layer(es, max_attempts=3)

    @mock.patch("elasticsearch.Elasticsearch")
    def test_ssl_error(self, es):
        es.cluster.health.side_effect = elasticsearch.ConnectionError(
            "N/A",
            "[SSL: UNKNOWN_PROTOCOL] unknown protocol (_ssl.c:719)",
            urllib3.exceptions.SSLError("[SSL: UNKNOWN_PROTOCOL] unknown protocol (_ssl.c:719)"),
        )
        with pytest.raises(exceptions.SystemSetupError, match="Could not connect to cluster via https. Is this an https endpoint?"):
            client.wait_for_rest_layer(es, max_attempts=3)


class TestAsyncConnection:
    @pytest.mark.asyncio
    async def test_enable_cleanup_close(self):
        connection = AIOHttpConnection()
        # pylint: disable=protected-access
        assert connection._enable_cleanup_closed is True

        connection = AIOHttpConnection(enable_cleanup_closed=False)
        # pylint: disable=protected-access
        assert connection._enable_cleanup_closed is False
