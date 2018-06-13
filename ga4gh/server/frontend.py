"""
The Flask frontend for the GA4GH API.

TODO Document properly.
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import datetime
import socket
import urlparse
import functools
import json

import flask
import flask.ext.cors as cors
from flask.ext.oidc import OpenIDConnect
from flask import Flask, jsonify, render_template, request
import humanize
import werkzeug
import oic
# from oic.oic import AuthorizationRequest, Client
import oic.oauth2
import oic.oic.message as message
# from oic.utils.http_util import Redirect
from oauth2client.client import OAuth2Credentials
import requests
import logging
from logging import StreamHandler
from werkzeug.contrib.cache import FileSystemCache

import pkg_resources

import ga4gh.server
import ga4gh.server.backend as backend
import ga4gh.server.datamodel as datamodel
import ga4gh.server.exceptions as exceptions
import ga4gh.server.datarepo as datarepo
import ga4gh.server.auth as auth
import ga4gh.server.network as network
import ga4gh.server.DP as DP
import ga4gh.server.NCIT as NCIT

import ga4gh.schemas.protocol as protocol

from ga4gh.client import client
import base64

SEARCH_ENDPOINT_METHODS = ['POST', 'OPTIONS']
SECRET_KEY_LENGTH = 24
LOGIN_ENDPOINT_METHODS = ['GET', 'POST']

app = flask.Flask(__name__)
assert not hasattr(app, 'urls')
app.urls = []

requires_auth = auth.auth_decorator(app)

# Edit this for flask-oidc, the endpoints are in the client_secrets.json file
config_path = '/'.join(('.','config','client_secrets.json'))

app.config.update({
    'SECRET_KEY': "key",
    'TESTING': False,
    'DEBUG': False,
    'OIDC_CLIENT_SECRETS': pkg_resources.resource_filename(__name__, config_path),
    'OIDC_ID_TOKEN_COOKIE_SECURE': False,
    'OIDC_REQUIRE_VERIFIED_EMAIL': False,
})

# For configuration of Flask-Oidc
oidc = OpenIDConnect(app)


class NoConverter(werkzeug.routing.BaseConverter):
    """
    A converter that allows the routing matching algorithm to not
    match on certain literal terms

    This is needed because if there are e.g. two routes:

    /callsets/search
    /callsets/<id>

    A request for /callsets/search will get routed to
    the second, which is not what we want.
    """
    def __init__(self, map, *items):
        werkzeug.routing.BaseConverter.__init__(self, map)
        self.items = items

    def to_python(self, value):
        if value in self.items:
            raise werkzeug.routing.ValidationError()
        return value


app.url_map.converters['no'] = NoConverter


class ServerStatus(object):
    """
    Generates information about the status of the server for display
    """
    def __init__(self):
        self.startupTime = datetime.datetime.now()

    def getConfiguration(self):
        """
        Returns a list of configuration (key, value) tuples
        that are useful for users to view on an information page.
        Note that we should be careful here not to leak sensitive
        information. For example, keys and paths of data files should
        not be returned.
        """
        # TODO what other config keys are appropriate to export here?
        keys = [
            'DEBUG', 'REQUEST_VALIDATION',
            'DEFAULT_PAGE_SIZE', 'MAX_RESPONSE_LENGTH', 'LANDING_MESSAGE_HTML'
        ]
        return [(k, app.config[k]) for k in keys]

    def getPreciseUptime(self):
        """
        Returns the server precisely.
        """
        return self.startupTime.strftime("%H:%M:%S %d %b %Y")

    def getLandingMessageHtml(self):
        filePath = app.config.get('LANDING_MESSAGE_HTML')
        try:
            htmlFile = open(filePath, 'r')
            html = htmlFile.read()
            htmlFile.close()
        except:
            html = flask.render_template("landing_message.html")
        return html

    def getNaturalUptime(self):
        """
        Returns the uptime in a human-readable format.
        """
        return humanize.naturaltime(self.startupTime)

    def getProtocolVersion(self):
        """
        Returns the GA4GH protocol version we support.
        """
        return protocol.version

    def getServerVersion(self):
        """
        Returns the software version of this server.
        """
        return ga4gh.server.__version__

    def getUrls(self):
        """
        Returns the list of (httpMethod, URL) tuples that this server
        supports.
        """
        app.urls.sort()
        return app.urls

    def getDatasets(self):
        """
        Returns the list of datasetIds for this backend
        """
        return app.backend.getDataRepository().getDatasets()

    def getExperiments(self):
        """
        Returns the list of experimentIds for this backend
        """
        return app.backend.getDataRepository().getExperiments()

    def getAnalyses(self):
        """
        Returns the list of analysisIds for this backend
        """
        return app.backend.getDataRepository().getAnalyses()

    def getVariantSets(self, datasetId):
        """
        Returns the list of variant sets for the dataset
        """
        return app.backend.getDataRepository().getDataset(
            datasetId).getVariantSets()

    def getFeatureSets(self, datasetId):
        """
        Returns the list of feature sets for the dataset
        """
        return app.backend.getDataRepository().getDataset(
            datasetId).getFeatureSets()

    def getContinuousSets(self, datasetId):
        """
        Returns the list of continuous sets for the dataset
        """
        return app.backend.getDataRepository().getDataset(
            datasetId).getContinuousSets()

    def getReadGroupSets(self, datasetId):
        """
        Returns the list of ReadGroupSets for the dataset
        """
        return app.backend.getDataRepository().getDataset(
            datasetId).getReadGroupSets()

    def getReferenceSets(self):
        """
        Returns the list of ReferenceSets for this server.
        """
        return app.backend.getDataRepository().getReferenceSets()

    def getVariantAnnotationSets(self, datasetId):
        """
        Returns the list of ReferenceSets for this server.
        """
        # TODO this should be displayed per-variant set, not per dataset.
        variantAnnotationSets = []
        dataset = app.backend.getDataRepository().getDataset(datasetId)
        for variantSet in dataset.getVariantSets():
            variantAnnotationSets.extend(
                variantSet.getVariantAnnotationSets())
        return variantAnnotationSets

    def getPhenotypeAssociationSets(self, datasetId):
        return app.backend.getDataRepository().getDataset(
            datasetId).getPhenotypeAssociationSets()

    def getRnaQuantificationSets(self, datasetId):
        """
        Returns the list of RnaQuantificationSets for this server.
        """
        return app.backend.getDataRepository().getDataset(
            datasetId).getRnaQuantificationSets()

    def getPeers(self):
        """
        Returns the list of peers.
        """
        return app.backend.getDataRepository().getPeers()

    def getOntologyByName(self, name):
        """
        Returns the list of ontologies.
        """
        return app.backend.getDataRepository().getOntologyByName(name)

def reset():
    """
    Resets the flask app; used in testing
    """
    app.config.clear()
    configStr = 'ga4gh.server.serverconfig:FlaskDefaultConfig'
    app.config.from_object(configStr)


def _configure_backend(app):
    """A helper function used just to help modularize the code a bit."""
    # Allocate the backend
    # We use URLs to specify the backend. Currently we have file:// URLs (or
    # URLs with no scheme) for the SqlDataRepository, and special empty:// and
    # simulated:// URLs for empty or simulated data sources.
    dataSource = urlparse.urlparse(app.config["DATA_SOURCE"], "file")

    if dataSource.scheme == "simulated":
        # Ignore the query string
        randomSeed = app.config["SIMULATED_BACKEND_RANDOM_SEED"]
        numCalls = app.config["SIMULATED_BACKEND_NUM_CALLS"]
        variantDensity = app.config["SIMULATED_BACKEND_VARIANT_DENSITY"]
        numVariantSets = app.config["SIMULATED_BACKEND_NUM_VARIANT_SETS"]
        numReferenceSets = app.config[
            "SIMULATED_BACKEND_NUM_REFERENCE_SETS"]
        numReferencesPerReferenceSet = app.config[
            "SIMULATED_BACKEND_NUM_REFERENCES_PER_REFERENCE_SET"]
        numAlignmentsPerReadGroup = app.config[
            "SIMULATED_BACKEND_NUM_ALIGNMENTS_PER_READ_GROUP"]
        numReadGroupsPerReadGroupSet = app.config[
            "SIMULATED_BACKEND_NUM_READ_GROUPS_PER_READ_GROUP_SET"]
        numPhenotypeAssociations = app.config[
            "SIMULATED_BACKEND_NUM_PHENOTYPE_ASSOCIATIONS"]
        numPhenotypeAssociationSets = app.config[
            "SIMULATED_BACKEND_NUM_PHENOTYPE_ASSOCIATION_SETS"]
        numRnaQuantSets = app.config[
            "SIMULATED_BACKEND_NUM_RNA_QUANTIFICATION_SETS"]
        numExpressionLevels = app.config[
            "SIMULATED_BACKEND_NUM_EXPRESSION_LEVELS_PER_RNA_QUANT_SET"]

        dataRepository = datarepo.SimulatedDataRepository(
            randomSeed=randomSeed, numCalls=numCalls,
            variantDensity=variantDensity, numVariantSets=numVariantSets,
            numReferenceSets=numReferenceSets,
            numReferencesPerReferenceSet=numReferencesPerReferenceSet,
            numReadGroupsPerReadGroupSet=numReadGroupsPerReadGroupSet,
            numAlignments=numAlignmentsPerReadGroup,
            numPhenotypeAssociations=numPhenotypeAssociations,
            numPhenotypeAssociationSets=numPhenotypeAssociationSets,
            numRnaQuantSets=numRnaQuantSets,
            numExpressionLevels=numExpressionLevels)
    elif dataSource.scheme == "empty":
        dataRepository = datarepo.EmptyDataRepository()
    elif dataSource.scheme == "file":
        path = os.path.join(dataSource.netloc, dataSource.path)
        dataRepository = datarepo.SqlDataRepository(path)
        dataRepository.open(datarepo.MODE_READ)
    else:
        raise exceptions.ConfigurationException(
            "Unsupported data source scheme: " + dataSource.scheme)
    theBackend = backend.Backend(dataRepository)
    theBackend.setRequestValidation(app.config["REQUEST_VALIDATION"])
    theBackend.setDefaultPageSize(app.config["DEFAULT_PAGE_SIZE"])
    theBackend.setMaxResponseLength(app.config["MAX_RESPONSE_LENGTH"])
    return theBackend


def configure(configFile=None, baseConfig="ProductionConfig",
              port=8000, extraConfig={}):
    """
    TODO Document this critical function! What does it do? What does
    it assume?
    """
    file_handler = StreamHandler()
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)
    configStr = 'ga4gh.server.serverconfig:{0}'.format(baseConfig)
    app.config.from_object(configStr)
    if os.environ.get('GA4GH_CONFIGURATION') is not None:
        app.config.from_envvar('GA4GH_CONFIGURATION')
    if configFile is not None:
        app.config.from_pyfile(configFile)
    app.config.update(extraConfig.items())
    # Setup file handle cache max size
    datamodel.fileHandleCache.setMaxCacheSize(
        app.config["FILE_HANDLE_CACHE_MAX_SIZE"])
    # Setup CORS
    try:
        cors.CORS(app, allow_headers='Content-Type')
    except AssertionError:
        pass
    app.serverStatus = ServerStatus()

    app.backend = _configure_backend(app)
    if app.config.get('SECRET_KEY'):
        app.secret_key = app.config['SECRET_KEY']
    elif app.config.get('OIDC_PROVIDER'):
        raise exceptions.ConfigurationException(
            'OIDC configuration requires a secret key')
    if app.config.get('CACHE_DIRECTORY'):
        app.cache_dir = app.config['CACHE_DIRECTORY']
    else:
        app.cache_dir = '/tmp/ga4gh'
    app.cache = FileSystemCache(
        app.cache_dir, threshold=5000, default_timeout=600, mode=384)
    # Peer service initialization
    network.initialize(
        app.config.get('INITIAL_PEERS'),
        app.backend.getDataRepository(),
        app.logger)
    app.oidcClient = None
    app.myPort = port
    if app.config.get('AUTH0_ENABLED'):
        emails = app.config.get('AUTH0_AUTHORIZED_EMAILS', '').split(',')
        [auth.authorize_email(e, app.cache) for e in emails]
    if "OIDC_PROVIDER" in app.config:
        # The oic client. If we're testing, we don't want to verify
        # SSL certificates
        app.oidcClient = oic.oic.Client(
            verify_ssl=('TESTING' not in app.config))
        try:
            app.oidcClient.provider_config(app.config['OIDC_PROVIDER'])
        except requests.exceptions.ConnectionError:
            configResponse = message.ProviderConfigurationResponse(
                issuer=app.config['OIDC_PROVIDER'],
                authorization_endpoint=app.config['OIDC_AUTHZ_ENDPOINT'],
                token_endpoint=app.config['OIDC_TOKEN_ENDPOINT'],
                revocation_endpoint=app.config['OIDC_TOKEN_REV_ENDPOINT'])
            app.oidcClient.handle_provider_config(configResponse,
                                                  app.config['OIDC_PROVIDER'])

        # The redirect URI comes from the configuration.
        # If we are testing, then we allow the automatic creation of a
        # redirect uri if none is configured
        redirectUri = app.config.get('OIDC_REDIRECT_URI')
        if redirectUri is None and app.config.get('TESTING'):
            redirectUri = 'https://{0}:{1}/oauth2callback'.format(
                socket.gethostname(), app.myPort)
        app.oidcClient.redirect_uris = [redirectUri]
        if redirectUri is []:
            raise exceptions.ConfigurationException(
                'OIDC configuration requires a redirect uri')

        # We only support dynamic registration while testing.
        if ('registration_endpoint' in app.oidcClient.provider_info and
           app.config.get('TESTING')):
            app.oidcClient.register(
                app.oidcClient.provider_info["registration_endpoint"],
                redirect_uris=[redirectUri])
        else:
            response = message.RegistrationResponse(
                client_id=app.config['OIDC_CLIENT_ID'],
                client_secret=app.config['OIDC_CLIENT_SECRET'],
                redirect_uris=[redirectUri],
                verify_ssl=False)
            app.oidcClient.store_registration_info(response)


def chooseReturnMimetype(request):
    mimetype = None
    if hasattr(request, 'accept_mimetypes'):
        mimetype = request.accept_mimetypes.best_match(protocol.MIMETYPES)
    if mimetype is None:
        mimetype = protocol.MIMETYPES[0]
    return mimetype


def getFlaskResponse(responseString, httpStatus=200,
                     mimetype="application/json"):
    """
    Returns a Flask response object for the specified data and HTTP status.
    """
    return flask.Response(responseString, status=httpStatus, mimetype=mimetype)


### ======================================================================= ###
### FEDERATION
### ======================================================================= ###
def federation(endpoint, request, return_mimetype, request_type='POST'):
    """
    Federate the queries by iterating through the peer list and merging the
    result.

    Parameters:
    ===========
    endpoint: method
        Method of a datamodel object that populates the response
    request: string
        Request send along with the query, like: id for GET requests
    return_mimetype: string
        'http/json or application/json'
    request_type: string
        Specify whether the request is a "GET" or a "POST" request

    Returns:
    ========
    responseObject: json string
        Merged responses from the servers. responseObject structure:

    {
    "status": {
        "Successful communications": <number>,
        "Known peers": <number>,
        "Valid response": <true|false>,
        "Queried peers": <number>
        },
    "results": [
            {
            "datasets": [
                    {record1},
                    {record2},
                    ...
                    {recordN},
                ]
            }
        ]
    }

    """
    request_dictionary = flask.request
    if 'Authorization' in request_dictionary.headers:
        authz_token = int(request_dictionary.headers['Authorization'])
    else:
        authz_token = -1

    # Self query
    responseObject = {}
    responseObject['results'] = []
    responseObject['status'] = list()
    try:
        responseObject['results'] = [json.loads(
            endpoint(
                request, 
                return_mimetype=return_mimetype,
                tier=authz_token,
                )
            )]

        responseObject['status'].append(200)
    except exceptions.ObjectWithIdNotFoundException as error:
        responseObject['status'].append(404)
    except exceptions.NotFoundException as error:
        responseObject['status'].append(404)
        if request_type == 'POST': responseObject['results'].append({})

    # Peer queries
    # Apply federation by default or if it was specifically requested
    if ('Federation' not in request_dictionary.headers or \
            request_dictionary.headers['Federation'] == 'True'):

        # Iterate through all peers
        for peer in app.serverStatus.getPeers():
            # Generate the same call on the peer
            uri = request_dictionary.url.replace(
                request_dictionary.host_url,
                peer.getUrl(),
                )
            # federation field must be set to False to avoid infinite loop
            header = {
                'Content-Type': return_mimetype,
                'Accept': return_mimetype,
                'Federation': 'False',
                'Authorization': authz_token,
            }

            # Make the call
            try:
                if request_type == 'GET':
                    response = requests.Session().get(
                        uri,
                        headers=header,
                        )
                elif request_type == 'POST':
                    response = requests.Session().post(
                        uri,
                        json=json.loads(request),
                        headers=header,
                        )
                else:
                    #TODO: Raise error
                    pass

                print('  >> peer call: {0} - {1}'.format(
                    uri,
                    response.status_code,
                    ))

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError):
                responseObject['status'].append(503)

                print('  >> peer call: {0} - {1}'.format(
                    uri,
                    'SERVER IS DOWN OR DID NOT RESPONSE!',
                    ))
            else:
                responseObject['status'].append(response.status_code)
                # If the call was successful append the results
                if response.status_code == 200:

                    if request_type == 'GET':
                        responseObject['results'].append(
                            response.json()['results'][0])

                    elif request_type == 'POST':
                        peer_response = response.json()['results'][0]

                        if not responseObject['results'][0]:
                            responseObject['results'] = [peer_response]
                        else:
                            for key in peer_response:
                                #TODO: handle truncated responses; for now increased default page_size to 300
                                if key=='nextPageToken':
                                    continue
                                for record in peer_response[key]:
                                    responseObject['results'][0][key].append(record)

    # If no result has been found on any of the servers raise an error
    if not responseObject['results'] or not responseObject['results'][0]:
        if request_type == 'GET':
            raise exceptions.ObjectWithIdNotFoundException(request)
        elif request_type == 'POST':
            raise exceptions.ObjectWithIdNotFoundException(json.loads(request))

    # Reformat the status response
    responseObject['status'] = {
        'Known peers': \
            # All the peers plus self
            len(app.serverStatus.getPeers()) + 1,
        'Queried peers': \
            # Queried means http status code 200 and 404
            responseObject['status'].count(200) + \
            responseObject['status'].count(404),
        # Successful means http status code 200
        'Successful communications': \
            # Successful means http status code 200
            responseObject['status'].count(200),
        'Valid response': \
            # Invalid by default
            False
        }
    
    # Decide on valid response
    if responseObject['status']['Known peers'] == \
            responseObject['status']['Queried peers']:
        if request_type == 'GET':
            if responseObject['status']['Successful communications'] >= 1:
                responseObject['status']['Valid response'] = True
        elif request_type == 'POST':
            if responseObject['status']['Successful communications'] == \
                    responseObject['status']['Queried peers']:
                responseObject['status']['Valid response'] = True

    return json.dumps(responseObject)

# testing method for access roles through tokens
def getAccessLevels(token):

    token_payload = token.split(".")[1]

    # make sure token is padded properly for b64 decoding
    padding = len(token_payload) % 4
    if padding != 0:
        token_payload += '=' * (4 - padding)
    decoded_payload = base64.b64decode(token_payload)

    parsed_payload = json.loads(decoded_payload)
    access_levels = parsed_payload["access_levels"]

    # setting defaults
    results = {
        'tier': -1,
        'groups': []
    }

    for role in access_levels:
        if role.isdigit():
            results['tier'] = int(role)
        else:
            results['groups'].append(role)

    return results

### ======================================================================= ###
### FEDERATION ENDS
### ======================================================================= ###

def handleHttpPost(request, endpoint):
    """
    Handles the specified HTTP POST request, which maps to the specified
    protocol handler endpoint and protocol request class.
    """
    if request.mimetype and request.mimetype not in protocol.MIMETYPES:
        raise exceptions.UnsupportedMediaTypeException()
    return_mimetype = chooseReturnMimetype(request)
    request = request.get_data()
    if request == '' or request is None:
        request = '{}'
### ======================================================================= ###
### FEDERATION
### ======================================================================= ###
    responseStr = federation(
        endpoint,
        request,
        return_mimetype=return_mimetype,
        request_type='POST'
        )
### ======================================================================= ###
### FEDERATION ENDS
### ======================================================================= ###
    return getFlaskResponse(responseStr, mimetype=return_mimetype)


def handleList(endpoint, request):
    """
    Handles the specified HTTP GET request, mapping to a list request
    """
    return_mimetype = chooseReturnMimetype(request)
    responseStr = endpoint(request.get_data(), return_mimetype=return_mimetype)
    return getFlaskResponse(responseStr, mimetype=return_mimetype)


def handleHttpGet(id_, endpoint):
    """
    Handles the specified HTTP GET request, which maps to the specified
    protocol handler endpoint and protocol request class
    """
    request = flask.request
    return_mimetype = chooseReturnMimetype(request)
### ======================================================================= ###
### FEDERATION
### ======================================================================= ###
    responseStr = federation(
        endpoint,
        id_,
        return_mimetype=return_mimetype,
        request_type='GET'
        )
### ======================================================================= ###
### FEDERATION ENDS
### ======================================================================= ###
    return getFlaskResponse(responseStr, mimetype=return_mimetype)


def handleHttpOptions():
    """
    Handles the specified HTTP OPTIONS request.
    """
    response = getFlaskResponse("")
    response.headers.add("Access-Control-Request-Methods", "GET,POST,OPTIONS")
    return response


@app.errorhandler(Exception)
def handleException(exception):
    """
    Handles an exception that occurs somewhere in the process of handling
    a request.
    """
    serverException = exception
    if not isinstance(exception, exceptions.BaseServerException):
        with app.test_request_context():
            app.log_exception(exception)
        serverException = exceptions.getServerError(exception)
    error = serverException.toProtocolElement()
    # If the exception is being viewed by a web browser, we can render a nicer
    # view.
    if flask.request and 'Accept' in flask.request.headers and \
            flask.request.headers['Accept'].find('text/html') != -1:
        message = "<h1>Error {}</h1><pre>{}</pre>".format(
                    serverException.httpStatus,
                    protocol.toJson(error))
        if serverException.httpStatus == 401 \
                or serverException.httpStatus == 403:
            message += "Please try <a href=\"/login\">logging in</a>."
        return message
    else:
        # Errors aren't well defined enough to use protobuf, even if requested
        return_mimetype = 'application/json'
        responseStr = protocol.serialize(error, return_mimetype)
        return getFlaskResponse(responseStr, serverException.httpStatus,
                                mimetype=return_mimetype)


# Added by Kevin Chan
def requires_token(f):
    """
    Decorator function that ensures that the token is valid, if the token is
    invalid or expired, the user will be redirected to the login page. Much of
    the authorization code flow is done solely by the function decorator
    @oidc.require_login
    """
    @functools.wraps(f)
    def decorated(*args, **kargs):
        if app.config.get("KEYCLOAK"):
            redirectUri = 'http://{0}:{1}{2}'.format(
                    socket.gethostbyname(
                        socket.gethostname()),
                    app.myPort,
                    flask.request.path)
            try:
                info = oidc.user_getinfo(['sub'])
                tokenResponse = OAuth2Credentials.from_json(
                    oidc.credentials_store[info.get('sub')]
                    ).token_response
                introspectArgs = {
                    "token": tokenResponse["access_token"],
                    "client_id": oidc.client_secrets["client_id"],
                    "client_secret": oidc.client_secrets["client_secret"],
                    "refresh_token": tokenResponse["refresh_token"],
                }
            except:
                return flask.redirect(redirectUri)
            userInfo = requests.post(url=oidc.client_secrets[
                "token_introspection_uri"
                ],
                data=introspectArgs)

            if userInfo.status_code != 200:
                raise exceptions.NotAuthenticatedException()
        return f(*args, **kargs)
    return decorated

def requires_session(f):
    """
    Testing: decorator for ensuring we have valid tyk access and an authenticated flask session
    Modified from Kevin's original use case to grab tokens from session without using flask-oidc login
    Authentication in this scenario is mostly handled by the Tyk API gateway and its middleware
    Testing this out as a means of flask session management. Shouldn't be used with REST endpoints
    """

    @functools.wraps(f)
    def decorated(*args, **kargs):
        if app.config.get("TYK_ENABLED"):

            redirect_uri = 'http://{0}:{1}{2}'.format(
                app.config.get('TYK_SERVER'),
                app.config.get('TYK_PORT'),
                app.config.get('TYK_LISTEN_PATH')
            )

            if "state" not in flask.session:
                flask.session["state"] = flask.request.args.get("session_state")

            try:
                flask.session["access_token"] = flask.request.headers["X-AccessToken"]
                flask.session["refresh_token"] = flask.request.headers["X-RefreshToken"]

                # for making requests during session
                flask.session["id_token"] = flask.request.headers["Authorization"][7:]

            except:
                return flask.redirect(redirect_uri)

            introspectArgs = {
                "token": flask.session["access_token"],
                "client_id": oidc.client_secrets["client_id"],
                "client_secret": oidc.client_secrets["client_secret"],
                "refresh_token": flask.session["refresh_token"]
            }

            userInfo = requests.post(
                url=oidc.client_secrets["token_introspection_uri"],
                data=introspectArgs
            )

            if userInfo.status_code != 200:
                raise exceptions.NotAuthenticatedException()

        return f(*args, **kargs)
    return decorated

def startLogin():
    """
    If we are not logged in, this generates the redirect URL to the OIDC
    provider and returns the redirect response
    :return: A redirect response to the OIDC provider
    """
    flask.session["state"] = oic.oauth2.rndstr(SECRET_KEY_LENGTH)
    flask.session["nonce"] = oic.oauth2.rndstr(SECRET_KEY_LENGTH)
    args = {
        "client_id": app.oidcClient.client_id,
        "response_type": "code",
        "scope": ["openid", "profile"],
        "nonce": flask.session["nonce"],
        "redirect_uri": app.oidcClient.redirect_uris[0],
        "state": flask.session["state"]
    }

    result = app.oidcClient.do_authorization_request(
        request_args=args, state=flask.session["state"])
    return flask.redirect(result.url)


@app.before_request
def checkAuthentication():
    """
    The request will have a parameter 'key' if it came from the command line
    client, or have a session key of 'key' if it's the browser.
    If the token is not found, start the login process.

    If there is no oidcClient, we are running naked and we don't check.
    If we're being redirected to the oidcCallback we don't check.

    :returns None if all is ok (and the request handler continues as usual).
    Otherwise if the key was in the session (therefore we're in a browser)
    then startLogin() will redirect to the OIDC provider. If the key was in
    the request arguments, we're using the command line and just raise an
    exception.
    """
    if app.oidcClient is None:
        return
    if flask.request.endpoint == 'oidcCallback':
        return
    key = flask.session.get('key') or flask.request.args.get('key')
    if key is None or not app.cache.get(key):
        if 'key' in flask.request.args:
            raise exceptions.NotAuthenticatedException()
        else:
            return startLogin()


def handleFlaskGetRequest(id_, flaskRequest, endpoint):
    """
    Handles the specified flask request for one of the GET URLs
    Invokes the specified endpoint to generate a response.
    """
    if flaskRequest.method == "GET":
        return handleHttpGet(id_, endpoint)
    else:
        raise exceptions.MethodNotAllowedException()


def handleFlaskListRequest(id_, flaskRequest, endpoint):
    """
    Handles the specified flask list request for one of the GET URLs.
    Invokes the specified endpoint to generate a response.
    """

    return handleList(endpoint, flaskRequest)


def handleFlaskPostRequest(flaskRequest, endpoint):
    """
    Handles the specified flask request for one of the POST URLS
    Invokes the specified endpoint to generate a response.
    """
    if flaskRequest.method == "POST":
        return handleHttpPost(flaskRequest, endpoint)
    elif flaskRequest.method == "OPTIONS":
        return handleHttpOptions()
    else:
        raise exceptions.MethodNotAllowedException()


class DisplayedRoute(object):
    """
    Registers that a route should be displayed on the html page
    """
    def __init__(
            self, path, postMethod=False, pathDisplay=None):
        self.path = path
        self.methods = None
        if postMethod:
            methodDisplay = 'POST'
            self.methods = SEARCH_ENDPOINT_METHODS
        else:
            methodDisplay = 'GET'
        if pathDisplay is None:
            pathDisplay = path
        app.urls.append((methodDisplay, pathDisplay))

    def __call__(self, func):
        if self.methods is None:
            app.add_url_rule(self.path, func.func_name, func)
        else:
            app.add_url_rule(
                self.path, func.func_name, func, methods=self.methods)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return result
        return wrapper


@app.route('/', methods=LOGIN_ENDPOINT_METHODS)
@requires_session
def index():
    response = flask.render_template('index.html',
                                     info=app.serverStatus)
    if app.config.get('AUTH0_ENABLED'):
        key = (flask.request.args.get('key'))
        try:
            print(key)
            profile = app.cache.get(key)
        except:
            raise exceptions.NotAuthorizedException()
        if (profile):
            return response
        else:
            exceptions.NotAuthenticatedException()
    else:
        return response


### ======================================================================= ###
### FRONT END
### ======================================================================= ###
@app.route('/candig', methods=LOGIN_ENDPOINT_METHODS)
@requires_session
def candig():
    datasetId = "WyJNRVRBREFUQSJd";
    return flask.render_template('candig.html', session_id=flask.session["id_token"], datasetId=datasetId)

@app.route('/candig_patients', methods=LOGIN_ENDPOINT_METHODS)
@requires_session
def candig_patients():
    return flask.render_template('candig_patients.html', session_id=flask.session["id_token"])

@app.route('/igv', methods=LOGIN_ENDPOINT_METHODS)
@requires_session
def candig_igv():
    return flask.render_template('candig_igv.html', session_id=flask.session["id_token"])

@app.route('/gene_search', methods=LOGIN_ENDPOINT_METHODS)
def candig_gene_search():
    return flask.render_template('gene_search.html', session_id=flask.session["id_token"])

@DisplayedRoute('/variantsbygenesearch', postMethod=True)
def search_variant_by_gene_name():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchVariantsByGeneName)

### ======================================================================= ###
### FRONT END END
### ======================================================================= ###

### ======================================================================= ###
### Start TYK
### ======================================================================= ###

# proxy to oidc login
@app.route('/proxy')
def proxy():
    """
    *** this endpoint should ignore Tyk Authorization requirements ***

    All requests without an Authorization header should be proxied through
    this endpoint (except for authentication request). Tyk 'pre-auth' middleware
    will use this to ensure users are logged in

    :return: redirect call to the identity provider authentication point
    """

    redirect_uri = flask.request.args.get('redirectUri', None, type=str)

    if not redirect_uri:
        redirect_uri = 'http://{0}:{1}{2}'.format(
            app.config.get('TYK_SERVER'),
            app.config.get('TYK_PORT'),
            app.config.get('TYK_LISTEN_PATH')
        )

    idp_serv = app.config.get('KC_SERVER')
    idp_path = app.config.get('KC_LOGIN_REDIRECT')+redirect_uri

    return flask.redirect('http://{0}{1}'.format(idp_serv,idp_path))


@app.route('/logout_oidc', methods=LOGIN_ENDPOINT_METHODS)
def gateway_logout():
    """
    End both the flask + oidc login sessions. Requires user to be currently logged in

    :return: redirect to the gateway proxy page
    """

    try:
        url = oidc.client_secrets["logout_endpoint"]
        auth_bearer = 'Bearer ' + flask.session["access_token"]

        payload = {
            "refresh_token": flask.session["refresh_token"],
            "client_id": oidc.client_secrets["client_id"],
            "client_secret": oidc.client_secrets["client_secret"]
        }

        headers = {
            'Authorization': auth_bearer,
            'Content-Type': 'application/x-www-form-urlencoded',
        }

        requests.post(url, data=payload, headers=headers)
        flask.session.clear()

    except:
        # send to proxy endpoint after failing
        flask.request.url = flask.url_for('proxy')
        raise exceptions.NotAuthenticatedException()

    return flask.redirect(flask.url_for('proxy'))


@DisplayedRoute('/token', postMethod=True)
def token():
    """
        *** this endpoint should ignore Tyk Authorization requirements ***

        :return: an oidc id token to attach to subsequent request headers in the following format:

            Authorization: Bearer <token>

        As of now, the tyk 'pre-auth' js middleware handles the token
        grant API calls and unless there was an authentication error,
        the token should already be in the request header

        Allows token retrieval without having to use a flask session (ie. for REST API calls)
    """

    response = {}
    mimetype = "application/json"

    try:
        token = flask.request.headers["Authorization"][7:]
        response["token"] = token
        status = 200

    except:
        # get error details from the request
        response["error"] = flask.request.data
        status = 401

    return flask.Response(json.dumps(response), status=status, mimetype=mimetype)

### ======================================================================= ###
### END TYK
### ======================================================================= ###

@app.route('/concordance')
def concordance():
    gene = request.args.get('gene', '', type=str)
    if gene == '':
        return jsonify(result = 'Gene symbol is missing')
    concordance, freq, uniq = client.FederatedClient(
        ServerStatus().getPeers()).get_concordance(gene)
    abnormality = NCIT.NCIT().get_genetic_abnormalities(gene)
    disease = NCIT.NCIT().get_diseases(gene)
    return jsonify(result=render_template('concordance.html',
        concordance=concordance,
        freq=freq,
        uniq=uniq,
        abnormality=abnormality,
        disease=disease))


# New configuration added by Kevin Chan
@app.route("/login")
def login():
    if app.config.get('AUTH0_ENABLED'):
        if (flask.request.args.get('code')):
            return auth.render_key(app, key=flask.request.args.get('code'))
        else:
            return auth.render_login(
                app=app,
                scopes=app.config.get('AUTH0_SCOPES'),
                redirect_uri=app.config.get('AUTH0_CALLBACK_URL'),
                domain=app.config.get('AUTH0_HOST'),
                client_id=app.config.get('AUTH0_CLIENT_ID'))
    else:
        raise exceptions.NotFoundException()


@app.route('/callback')
def callback_handling():
    if app.config.get('AUTH0_ENABLED'):
        return auth.callback_maker(
            cache=app.cache,
            domain=app.config.get('AUTH0_HOST'),
            client_id=app.config.get('AUTH0_CLIENT_ID'),
            client_secret=app.config.get('AUTH0_CLIENT_SECRET'),
            redirect_uri=app.config.get('AUTH0_CALLBACK_URL'))()
    else:
        raise exceptions.NotFoundException()


@app.route("/logout")
@requires_auth
@cors.cross_origin(headers=['Content-Type', 'Authorization'])
def logout():
    key = flask.session['auth0_key']
    auth.logout(app.cache)
    url = 'https://{}/v2/logout?access_token={}&?client_id={}'.format(
        app.config.get('AUTH0_HOST'),
        key,
        app.config.get('AUTH0_CLIENT_ID'),
        app.config.get('AUTH0_CALLBACK_URL'))
    return flask.redirect(url)


@app.route('/favicon.ico')
@app.route('/robots.txt')
def robots():
    return flask.send_from_directory(
        app.static_folder, flask.request.path[1:])


@DisplayedRoute('/info')
@requires_auth
def getInfo():
    return handleFlaskGetRequest(
        None, flask.request, app.backend.runGetInfo)


@DisplayedRoute('/references/<id>')
@requires_auth
def getReference(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetReference)


@DisplayedRoute('/referencesets/<id>')
def getReferenceSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetReferenceSet)


@DisplayedRoute('/listreferencebases', postMethod=True)
def listReferenceBases():
    return handleFlaskListRequest(
        id, flask.request, app.backend.runListReferenceBases)


@DisplayedRoute('/callsets/search', postMethod=True)
def searchCallSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchCallSets)


@DisplayedRoute('/readgroupsets/search', postMethod=True)
def searchReadGroupSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchReadGroupSets)


@DisplayedRoute('/reads/search', postMethod=True)
def searchReads():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchReads)


@DisplayedRoute('/referencesets/search', postMethod=True)
def searchReferenceSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchReferenceSets)


@DisplayedRoute('/references/search', postMethod=True)
def searchReferences():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchReferences)


@DisplayedRoute('/variantsets/search', postMethod=True)
def searchVariantSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchVariantSets)


@DisplayedRoute('/variants/search', postMethod=True)
def searchVariants():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchVariants)


@DisplayedRoute('/genotypes/search', postMethod=True)
def searchGenotypes():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchGenotypes)


@DisplayedRoute('/variantannotationsets/search', postMethod=True)
def searchVariantAnnotationSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchVariantAnnotationSets)


@DisplayedRoute('/variantannotations/search', postMethod=True)
def searchVariantAnnotations():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchVariantAnnotations)


@DisplayedRoute('/datasets/search', postMethod=True)
@requires_auth
def searchDatasets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchDatasets)


@DisplayedRoute('/experiments/search', postMethod=True)
@requires_auth
def searchExperiments():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchExperiments)


@DisplayedRoute('/analyses/search', postMethod=True)
@requires_auth
def searchAnalyses():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchAnalyses)


@DisplayedRoute('/featuresets/search', postMethod=True)
@requires_auth
def searchFeatureSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchFeatureSets)


@DisplayedRoute('/features/search', postMethod=True)
@requires_auth
def searchFeatures():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchFeatures)


@DisplayedRoute('/continuoussets/search', postMethod=True)
@requires_auth
def searchContinuousSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchContinuousSets)


@DisplayedRoute('/continuous/search', postMethod=True)
@requires_auth
def searchContinuous():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchContinuous)


@DisplayedRoute('/biosamples/search', postMethod=True)
@requires_auth
def searchBiosamples():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchBiosamples)


@DisplayedRoute('/individuals/search', postMethod=True)
@requires_auth
def searchIndividuals():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchIndividuals)


### ======================================================================= ###
### METADATA
### ======================================================================= ###
@DisplayedRoute('/patients/search', postMethod=True)
@requires_auth
def searchPatients():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchPatients)

@DisplayedRoute('/enrollments/search', postMethod=True)
@requires_auth
def searchEnrollments():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchEnrollments)

@DisplayedRoute('/consents/search', postMethod=True)
@requires_auth
def searchConsents():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchConsents)

@DisplayedRoute('/diagnoses/search', postMethod=True)
@requires_auth
def searchDiagnoses():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchDiagnoses)

@DisplayedRoute('/samples/search', postMethod=True)
@requires_auth
def searchSamples():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchSamples)

@DisplayedRoute('/treatments/search', postMethod=True)
@requires_auth
def searchTreatments():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchTreatments)

@DisplayedRoute('/outcomes/search', postMethod=True)
@requires_auth
def searchOutcomes():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchOutcomes)

@DisplayedRoute('/complications/search', postMethod=True)
@requires_auth
def searchComplications():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchComplications)

@DisplayedRoute('/tumourboards/search', postMethod=True)
@requires_auth
def searchTumourboards():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchTumourboards)
### ======================================================================= ###
### METADATA END
### ======================================================================= ###


@DisplayedRoute('/peers/list', postMethod=True)
@requires_auth
def listPeers():
    return handleFlaskPostRequest(
        flask.request, app.backend.runListPeers)


@DisplayedRoute('/announce', postMethod=True)
@requires_auth
def announce():
    # We can't use the post handler here because we want detailed request
    # data.
    return app.backend.runAddAnnouncement(flask.request)


@DisplayedRoute(
    '/biosamples/<no(search):id>',
    pathDisplay='/biosamples/<id>')
@requires_auth
def getBiosample(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetBiosample)


@DisplayedRoute(
    '/individuals/<no(search):id>',
    pathDisplay='/individuals/<id>')
@requires_auth
def getIndividual(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetIndividual)

### ======================================================================= ###
### METADATA
### ======================================================================= ###
@DisplayedRoute(
    '/patients/<no(search):id>',
    pathDisplay='/patients/<id>')
@requires_auth
def getPatient(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetPatient)

@DisplayedRoute(
    '/enrollments/<no(search):id>',
    pathDisplay='/enrollments/<id>')
@requires_auth
def getEnrollment(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetEnrollment)

@DisplayedRoute(
    '/consents/<no(search):id>',
    pathDisplay='/consents/<id>')
@requires_auth
def getConsent(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetConsent)

@DisplayedRoute(
    '/diagnoses/<no(search):id>',
    pathDisplay='/diagnoses/<id>')
@requires_auth
def getDiagnosis(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetDiagnosis)

@DisplayedRoute(
    '/samples/<no(search):id>',
    pathDisplay='/samples/<id>')
@requires_auth
def getSample(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetSample)

@DisplayedRoute(
    '/treatments/<no(search):id>',
    pathDisplay='/treatments/<id>')
@requires_auth
def getTreatment(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetTreatment)

@DisplayedRoute(
    '/outcomes/<no(search):id>',
    pathDisplay='/outcomes/<id>')
@requires_auth
def getOutcome(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetOutcome)

@DisplayedRoute(
    '/complications/<no(search):id>',
    pathDisplay='/complications/<id>')
@requires_auth
def getComplication(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetComplication)

@DisplayedRoute(
    '/tumourboards/<no(search):id>',
    pathDisplay='/tumourboards/<id>')
@requires_auth
def getTumourboard(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetTumourboard)
### ======================================================================= ###
### METADATA END
### ======================================================================= ###


@DisplayedRoute('/rnaquantificationsets/search', postMethod=True)
@requires_auth
def searchRnaQuantificationSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchRnaQuantificationSets)


@DisplayedRoute('/rnaquantifications/search', postMethod=True)
@requires_auth
def searchRnaQuantifications():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchRnaQuantifications)


@DisplayedRoute('/expressionlevels/search', postMethod=True)
@requires_auth
def searchExpressionLevels():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchExpressionLevels)


@DisplayedRoute(
    '/variantsets/<no(search):id>',
    pathDisplay='/variantsets/<id>')
@requires_auth
def getVariantSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetVariantSet)


@DisplayedRoute(
    '/variants/<no(search):id>',
    pathDisplay='/variants/<id>')
@requires_auth
def getVariant(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetVariant)


@DisplayedRoute(
    '/readgroupsets/<no(search):id>',
    pathDisplay='/readgroupsets/<id>')
@requires_auth
def getReadGroupSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetReadGroupSet)


@DisplayedRoute('/readgroups/<id>')
@requires_auth
def getReadGroup(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetReadGroup)


@DisplayedRoute(
    '/callsets/<no(search):id>',
    pathDisplay='/callsets/<id>')
@requires_auth
def getCallSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetCallSet)


@DisplayedRoute(
    '/featuresets/<no(search):id>',
    pathDisplay='/featuresets/<id>')
@requires_auth
def getFeatureSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetFeatureSet)


@DisplayedRoute(
    '/features/<no(search):id>',
    pathDisplay='/features/<id>')
@requires_auth
def getFeature(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetFeature)


@DisplayedRoute(
    '/continuoussets/<no(search):id>',
    pathDisplay='/continuoussets/<id>')
@requires_auth
def getcontinuousSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetContinuousSet)


@DisplayedRoute(
    '/rnaquantificationsets/<no(search):id>',
    pathDisplay='/rnaquantificationsets/<id>')
@requires_auth
def getRnaQuantificationSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetRnaQuantificationSet)


@DisplayedRoute(
    '/rnaquantifications/<no(search):id>',
    pathDisplay='/rnaquantifications/<id>')
@requires_auth
def getRnaQuantification(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetRnaQuantification)


@DisplayedRoute(
    '/expressionlevels/<no(search):id>',
    pathDisplay='/expressionlevels/<id>')
@requires_auth
def getExpressionLevel(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetExpressionLevel)


@app.route('/oauth2callback', methods=['GET'])
def oidcCallback():
    """
    Once the authorization provider has cleared the user, the browser
    is returned here with a code. This function takes that code and
    checks it with the authorization provider to prove that it is valid,
    and get a bit more information about the user (which we don't use).

    A token is generated and given to the user, and the authorization info
    retrieved above is stored against this token. Later, when a client
    connects with this token, it is assumed to be a valid user.

    :return: A display of the authentication token to use in the client. If
    OIDC is not configured, raises a NotImplementedException.
    """
    if app.oidcClient is None:
        raise exceptions.NotImplementedException()
    response = dict(flask.request.args.iteritems(multi=True))
    aresp = app.oidcClient.parse_response(
        message.AuthorizationResponse,
        info=response,
        sformat='dict')
    sessState = flask.session.get('state')
    respState = aresp['state']
    if (not isinstance(aresp, message.AuthorizationResponse) or
            respState != sessState):
        raise exceptions.NotAuthenticatedException()

    args = {
        "code": aresp['code'],
        "redirect_uri": app.oidcClient.redirect_uris[0],
        "client_id": app.oidcClient.client_id,
        "client_secret": app.oidcClient.client_secret
    }
    atr = app.oidcClient.do_access_token_request(
        scope="openid",
        state=respState,
        request_args=args)

    if not isinstance(atr, message.AccessTokenResponse):
        raise exceptions.NotAuthenticatedException()

    atrDict = atr.to_dict()
    if flask.session.get('nonce') != atrDict['id_token']['nonce']:
        raise exceptions.NotAuthenticatedException()
    key = oic.oauth2.rndstr(SECRET_KEY_LENGTH)
    flask.session['key'] = key
    token_data = aresp["code"], respState, atrDict
    app.cache.set(key, token_data)
    # flask.url_for is broken. It relies on SERVER_NAME for both name
    # and port, and defaults to 'localhost' if not found. Therefore
    # we need to fix the returned url
    indexUrl = flask.url_for('index', _external=True)
    indexParts = list(urlparse.urlparse(indexUrl))
    if ':' not in indexParts[1]:
        indexParts[1] = '{}:{}'.format(socket.gethostname(), app.myPort)
        indexUrl = urlparse.urlunparse(indexParts)
    response = flask.redirect(indexUrl)
    return response


@DisplayedRoute(
    '/datasets/<no(search):id>',
    pathDisplay='/datasets/<id>')
@requires_auth
def getDataset(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetDataset)


@DisplayedRoute(
    '/experiments/<no(search):id>',
    pathDisplay='/experiments/<id>')
@requires_auth
def getExperiment(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetExperiment)


@DisplayedRoute(
    '/analyses/<no(search):id>',
    pathDisplay='/analyses/<id>')
@requires_auth
def getAnalysis(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetAnalysis)


@DisplayedRoute(
    '/variantannotationsets/<no(search):id>',
    pathDisplay='/variantannotationsets/<id>')
@requires_auth
def getVariantAnnotationSet(id):
    return handleFlaskGetRequest(
        id, flask.request, app.backend.runGetVariantAnnotationSet)


@DisplayedRoute('/phenotypes/search', postMethod=True)
@requires_auth
def searchPhenotypes():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchPhenotypes)


@DisplayedRoute('/featurephenotypeassociations/search', postMethod=True)
@requires_auth
def searchGenotypePhenotypes():
    return handleFlaskPostRequest(
        flask.request,
        app.backend.runSearchGenotypePhenotypes)


@DisplayedRoute('/phenotypeassociationsets/search', postMethod=True)
@requires_auth
def searchPhenotypeAssociationSets():
    return handleFlaskPostRequest(
        flask.request, app.backend.runSearchPhenotypeAssociationSets)


# The below methods ensure that JSON is returned for various errors
# instead of the default, html


@app.errorhandler(401)
def unauthorizedHandler(errorString):
    return handleException(exceptions.UnauthorizedException(errorString))


@app.errorhandler(404)
def pathNotFoundHandler(errorString):
    return handleException(exceptions.PathNotFoundException())


@app.errorhandler(405)
def methodNotAllowedHandler(errorString):
    return handleException(exceptions.MethodNotAllowedException())


@app.errorhandler(403)
def notAuthenticatedHandler(errorString):
    return handleException(exceptions.NotAuthenticatedException(errorString))
