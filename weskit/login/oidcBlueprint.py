from flask import jsonify, request, Blueprint, redirect, abort
from flask import current_app as app
from flask_jwt_extended import (
    unset_jwt_cookies
)

import urllib
import json
import time
from base64 import b64decode

from weskit.login.utils import requester_and_cookieSetter

login = Blueprint('login', __name__, template_folder='templates')


###########################################################
#  Login / Logout / Tokenrenew / Oauth Callback Endpoint..#
###########################################################


@login.route('/login', methods=['GET'])
def loginFct(requestedURL=""):
    """
    Browser Login via Redirect to Keyclaok Form
    """
    url = app.OIDC_Login.oidc_config['authorization_endpoint']
    params = (
                 "?client_id=%s&"
                 "redirect_uri=%s&"
                 "scope=openid+email+profile&"
                 "access_type=offline&"
                 "response_type=code&"
                 "openid.realm=%s&"
                 "state=%s") % (
                 app.OIDC_Login.client_id,
                 urllib.parse.quote(
                     app.OIDC_Login.hostname + '/login/callback', safe=''
                 ),
                 app.OIDC_Login.realm,
                 urllib.parse.quote(requestedURL)
    )

    return redirect(url + params, code=302)


@login.route('/login', methods=['POST'])
def direct_auth():
    """
    Via Posting Login Credentials to /login
    {"username":"test","password":"test"}
    """
    if not request.is_json:
        abort(400)  # or any custom BadRequest message
    username = request.json.get('username', None)
    password = request.json.get('password', None)
    if not (username and password):
        return jsonify({"msg": "username or password missing"}), 401
    payload = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": app.OIDC_Login.client_id,
        "client_secret": app.OIDC_Login.client_secret
    }

    # Make request
    return requester_and_cookieSetter(payload, setcookies=False)


@login.route('/login/callback', methods=['GET'])
def callbackFunction():
    """
    The ODIC authenticator redirects to this endpoint after login success and sets an one time session code as param.
    This code can be used to obtain the access_token from the OIDC Identity provider. If this function is called by the
    client it will recieve a session cookie and an access token via cookie.
    Furthermore, the client will be redirected to the original requested endpoint.
    """

    code = request.args.get("code", None)
    # Payload
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "%s/login/callback" %
                        (app.OIDC_Login.hostname),
        "client_id": app.OIDC_Login.client_id,
        "client_secret": app.OIDC_Login.client_secret
    }

    if not code:
        return (
            jsonify(
                {'login': False, 'msg': 'login code missing'}
            ), 401
        )
    response_object = None

    # If redirect is requested
    redirectPath = request.args.get('state', None)
    if redirectPath:
        response_object = redirect(
            request.url_root.rstrip("/") + urllib.parse.unquote(redirectPath),
            code=302
        )

    # Make request
    return (requester_and_cookieSetter(payload, True, response_object))


@login.route('/login/logout', methods=['GET'])
def logoutFct():
    """
    This deletes the token cookies and removes the SSO session generated by
    the OIDC provider.
    """
    # ODIC host will return to this point after logout
    comebackURL = app.OIDC_Login.hostname + "/"

    url = app.OIDC_Login.oidc_config['end_session_endpoint']
    params = "?redirect_uri=%s" % (
        urllib.parse.quote(comebackURL, safe=''))

    # Initiate redirect
    oidc_logout = redirect(url + params, code=302)
    # Delete Token Cookies
    unset_jwt_cookies(oidc_logout)
    return (oidc_logout)


@login.route("/login/refresh", methods=['GET'])
def refresh_access_token(response_object=None):
    """
    This endpoint is called to refresh the access token be submitting the refresh token. I its automated called if an
    user is authenticated with a access token cookie which reaches half it lifetime. The response object is the render
    view of which is enriched with a new access token.
    """

    # Obtain the refresh cookie token name used by jwt_extended
    refreshCookieName = app.config["JWT_REFRESH_COOKIE_NAME"]

    # Check for existing refresh cookie return error if not is present
    if refreshCookieName not in request.cookies:
        if response_object:
            return response_object
        return jsonify(
            {'refresh': False, "msg": "Missing Refresh Cookie!"}
        ), 401

    # Check for existing refresh cookie return error if not is present
    if not refresh_token_timeOK(request.cookies[refreshCookieName]):
        if response_object:
            return response_object
        return jsonify(
            {'refresh': False, "msg": "Refresh Cookie Expired!"}
        ), 401

    # Prepare Header and Payload for the OIDC request
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": request.cookies[refreshCookieName],
        "client_id": app.OIDC_Login.client_id,
        "client_secret": app.OIDC_Login.client_secret
    }

    # Get an response from OIDC authenticator
    return requester_and_cookieSetter(payload, setcookies=True, response_object=response_object)


def refresh_token_timeOK(token):
    """
    This function extracts the users refresh_token and tries to obtain it's expiration date. If it is passed this
    function will return False by default and in cases of exceptions and True if the refresh token is still valid.
    """
    try:
        a = token.split('.')
        if len(a) == 3:
            return (json.loads(b64decode(a[1] + "==="))['exp'] >= time.time())
    except Exception as e:
        app.OIDC_Login.logger.info("Got Invalid Refresh Token!", e)
        return (False)
