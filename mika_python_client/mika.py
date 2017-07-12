# coding=utf-8
"""
This module is used to communicate with mika's API
"""
from __future__ import absolute_import, print_function, unicode_literals
import re
from urllib.parse import unquote_plus
import redis
import requests
from http import client as httplib

_base_url = ""
_api_key = ""

MSG_OK = 200
MSG_INVALID_REQ_TYPE = 100
MSG_MISSING_INFO_HASH = 101
MSG_MISSING_PEER_ID = 102
MSG_MISSING_PORT = 103
MSG_INVALID_PORT = 104
MSG_INVALID_INFO_HASH = 150
MSG_INVALID_PEER_ID = 151
MSG_INVALID_NUM_WANT = 152
MSG_INFO_HASH_NOT_FOUND = 480
MSG_INVALID_AUTH = 490
MSG_CLIENT_REQUEST_TOO_FAST = 500
MSG_GENERIC_ERROR = 900
MSG_MALFORMED_REQUEST = 901
MSG_QUERY_PARSE_FAIL = 902

messages = {
    MSG_INVALID_REQ_TYPE: b"Invalid request type",
    MSG_MISSING_INFO_HASH: b"info_hash missing from request",
    MSG_MISSING_PEER_ID: b"peer_id missing from request",
    MSG_MISSING_PORT: b"port missing from request",
    MSG_INVALID_PORT: b"Invalid port",
    MSG_INVALID_AUTH: b"Invalid passkey supplied",
    MSG_INVALID_INFO_HASH: b"Torrent info hash must be 20 characters",
    MSG_INVALID_PEER_ID: b"Peer ID Invalid",
    MSG_INVALID_NUM_WANT: b"num_want invalid",
    MSG_INFO_HASH_NOT_FOUND: b"Unknown infohash",
    MSG_CLIENT_REQUEST_TOO_FAST: b"Slow down there jimmy.",
    MSG_MALFORMED_REQUEST: b"Malformed request",
    MSG_GENERIC_ERROR: b"Generic Error",
    MSG_QUERY_PARSE_FAIL: b"Could not parse request"
}

class MikaException(Exception):
    pass


class ValidationError(MikaException):
    pass


class TrackerError(MikaException):
    pass


class BadResponse(TrackerError):
    pass


class DuplicateError(TrackerError):
    pass


class NotFoundError(TrackerError):
    pass
    e
def configure(base_url, key):
    """ Configured the modules required parameters used to make authenticated requests

    :param base_url: base url used for requests
    :type base_url: str
    :param key: Bots API Key
    :type key: str
    """
    global _base_url, _api_key
    _base_url = base_url
    _api_key = key


def bot_api_request(endpoint, method='GET', payload=None):
    """ Make an HTTP api request to the tracker using the configured irc key

    :param endpoint:
    :type endpoint:
    :param method:
    :type method:
    :param payload:
    :type payload:
    :return:
    :rtype: dict
    """
    url = _base_url + endpoint
    headers = {
        'X-IRCBOT-API-KEY': _api_key,
        'Content-type': 'application/json',
        'Accept': 'application/json'
    }
    if method == 'GET':
        r = requests.get(url, headers=headers)
    elif method == 'POST':
        r = requests.post(url, headers=headers, data=payload)
    else:
        r = requests.get(url, headers=headers)
    return r.json()


_ih_rx = re.compile("^[0-9a-zA-Z]{40}$")


def validate_info_hash(info_hash):
    info_hash = str(info_hash)
    if not _ih_rx.match(info_hash):
        raise ValidationError("Invalid info_hash supplied: {}".format(info_hash))
    return info_hash


def validate_torrent_id(torrent_id):
    if torrent_id <= 0:
        raise ValidationError("Invalid torrent_id supplied: {}".format(torrent_id))
    return torrent_id


class Client(object):
    """ A simple API client used to communicate with the tracker

    :param api_uri:
    :type api_uri:
    :param redis_host: redis host
    :type redis_host: unicode
    :param redis_port: Redis port
    :type redis_port: int
    :param redis_db: redis database to use
    :type redis_db: int
    :param verify: Verify tracker SSL cert
    :type verify: bool
    """

    def __init__(self, api_uri, username="dev", password="dev", redis_host="localhost",
                 redis_port=6379, redis_db=0, verify=False, timeout=3):
        self._api_uri = api_uri
        self._auth = (username, password) if username and password else None
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_db = redis_db
        self._redis = redis.StrictRedis(host=redis_host, port=int(redis_port), db=int(redis_db))
        self._verify = verify
        self._timeout = timeout

    def _request(self, path, method='get', payload=None, valid_codes=None):
        if valid_codes is None:
            valid_codes = []
        if method == "get":
            resp = requests.get(self._make_url(path), verify=self._verify, auth=self._auth, timeout=self._timeout)
        elif method == "post":
            resp = requests.post(self._make_url(path), json=payload, verify=self._verify,
                                 auth=self._auth, timeout=self._timeout)
        elif method == "delete":
            resp = requests.delete(self._make_url(path), verify=self._verify, auth=self._auth, timeout=self._timeout)
        else:
            raise NotImplementedError("Unsupported HTTP method: {}".format(method))
        if resp.status_code == httplib.NOT_FOUND:
            raise NotFoundError("Entity not found")
        elif resp.status_code == httplib.CONFLICT:
            raise DuplicateError("Entity already exists")
        elif not resp.ok and resp.status_code not in valid_codes:
            raise BadResponse("Received bad response from server: {}".format(resp.status_code))
        else:
            return resp

    def _make_url(self, path):
        return "".join([self._api_uri, path])

    def version(self):
        return self._request("/version").json()

    def uptime(self):
        return self._request("/uptime").json()

    def torrent_get(self, info_hash):
        return self._request("/torrent/{}".format(validate_info_hash(info_hash))).json()

    def torrent_get_all(self, torrent_ids):
        found, not_found = [], []
        for info_hash in torrent_ids:
            try:
                found.append(self.torrent_get(info_hash))
            except NotFoundError:
                not_found.append(info_hash)
        return found, not_found

    def torrent_add(self, info_hash, torrent_id, name):
        validate_info_hash(info_hash)
        validate_torrent_id(torrent_id)
        pl = {
            'info_hash': validate_info_hash(info_hash),
            'torrent_id': validate_torrent_id(torrent_id),
            'name': name
        }
        return self._request("/torrent", method='post', payload=pl)

    def torrent_del(self, info_hash):
        resp = self._request("/torrent/{}".format(info_hash), method='delete')
        if resp.ok:
            return True
        elif resp.status_code == httplib.NOT_FOUND:
            raise NotFoundError("Unknown info hash, cannot delete: {}".format(info_hash))
        else:
            raise BadResponse("Invalid response returned from tracker")

    def get_torrent_peers(self, info_hash):
        resp = self._request("/torrent/{}/peers".format(validate_info_hash(info_hash)))
        if resp.ok:
            peers = resp.json()
            for peer in peers:
                peer['peer_id'] = unquote_plus(peer['peer_id'])
            return peers
        else:
            raise Exception("ahh")

    def get_torrent_counts(self):
        """ Fetch and return a list of dictionary objects containing the current
        data related to seeder/leeder/snatch counts for all torrents currently
        tracked in the tracker

            [
                {
                    'leechers': 0,
                    'info_hash': '9c2f8f7f4996b2853509247504681dbe98e5d0c1',
                    'snatches': 0,
                    'seeders': 0,
                    'torrent_id': 1112
                }, ...
            ]

        :return: List of dictionaries with torrent stats
        :rtype: []dict
        """
        return self._request("/counts").json()

    def user_get_active(self, user_id):
        pass

    def user_get_incomplete(self, user_id):
        pass

    def user_get_complete(self, user_id):
        pass

    def user_get_hnr(self, user_id):
        pass

    def user_update(self, user_id, uploaded=None, downloaded=None, passkey=None, can_leech=None,
                    enabled=None):
        user = self.user_get(user_id)
        updated_data = {
            "name": user["username"],
            'uploaded': uploaded if uploaded is not None else user['uploaded'],
            'downloaded': downloaded if downloaded is not None else user['downloaded'],
            'can_leech': can_leech if can_leech is not None else user['can_leech'],
            'passkey': passkey if passkey is not None else user['passkey'],
            "enabled": enabled if enabled is not None else user["enabled"]
        }

        resp = self._request("/user/{}".format(user_id), 'post', payload=updated_data)
        if resp.status_code == httplib.ACCEPTED:
            return True
        else:
            raise BadResponse("Received bad response from server: {}".format(resp.status_code))

    def user_get(self, user_id):
        resp = self._request("/user/{}".format(user_id))
        if resp.ok:
            return resp.json()
        elif resp.status_code == httplib.NOT_FOUND:
            raise NotFoundError("Unknown user id: {}".format(user_id))
        else:
            raise BadResponse("Error fetching user api")

    def user_add(self, name, user_id, passkey, can_leech=True):
        self._request("/user", method='post', payload={
            'user_id': user_id,
            'passkey': passkey,
            'can_leech': can_leech,
            'name': name
        })
        return self.user_get(user_id)

    def user_del(self, user_id):
        resp = self._request("/user/{}".format(user_id), method="delete")
        return resp.ok

    def whitelist_del(self, prefix):
        resp = self._request("/whitelist/{}".format(prefix), method='delete')
        if resp.ok:
            return True
        elif resp.status_code == httplib.NOT_FOUND:
            raise NotFoundError("Unknown client prefix supplied: {}".format(prefix))
        else:
            raise BadResponse("Bad response from server: {}".format(resp.status_code))

    def whitelist_add(self, prefix, client_name):
        resp = self._request("/whitelist", method='post', payload={
            'prefix': prefix,
            'client': client_name
        })
        if resp.ok:
            return True
        elif resp.status_code == httplib.CONFLICT:
            raise DuplicateError(
                "Whitelist entry already exists: {}/{}".format(prefix, client_name))
        else:
            raise BadResponse("Bad response from server: {}".format(resp.status_code))

    def torrent_get_all_redis(self):
        torrents = []
        keys = self._redis.keys("t:t:*")
        for key in keys:
            try:
                key = key.decode()
            except UnicodeDecodeError:
                pass
            try:
                if len(key) != 44:
                    continue
                tor = self._redis.hgetall(key)
            except redis.ResponseError as err:
                print(err)
                print(key)
                break
            else:
                torrents.append(tor)
        return torrents

    def users_get_all_redis(self, sort="user_id"):
        users = []
        keys = [k for k in self._redis.keys("t:u:*")]
        for k in keys:
            try:
                k = k.decode()
                data = self._redis.hgetall(k)
                user = {
                    'passkey': data.get(b'passkey', "ERROR: PASSKEY NOT SET"),
                    'user_id': int(data.get(b'user_id', b"-1")),
                    'downloaded': int(data.get(b'downloaded', b"-1")),
                    'uploaded': int(data.get(b'uploaded', b"-1")),
                    'username': data.get(b'username', b"ERROR: NO USER!").decode(),
                    'enabled': data.get(b'enabled', b"0").decode()
                }
                users.append(user)
            except redis.ResponseError:
                # print("Dropping erroneous key: {}".format(k))
                # self._redis.delete(k)
                pass
            except Exception as err:
                print(err)
                print(data)
                print(k)
                break

        users.sort(key=lambda u: u[sort])
        return users

    def cleanup(self, delete=False):
        # Look for active/inactive user suffix keys etc. t:u:$id:*
        keys = [k for k in self._redis.keys("t:u:*")]
        old_keys = []
        for key in keys:
            if len(key.split(b":")) != 3:
                old_keys.append(key)
            else:
                user = self._redis.hgetall(key)
                self._validate_int_fields(key, user,
                                          [b'downloaded', b'uploaded', b'snatches', b'announces',
                                           b'corrupt'])
        for key in old_keys:
            print(key)
            if delete:
                self._redis.delete(key)
        # Look for peer suffix keys t:t:$ih:*
        keys = [k for k in self._redis.keys("t:t:*")]
        old_keys_2 = []
        for key in keys:
            k = key.split(b":")
            if len(k) != 3 or k[2].startswith(b"b'"):
                old_keys_2.append(key)
            else:
                # Look for old int based keys
                try:
                    int(k[2])
                except Exception:
                    torrent = self._redis.hgetall(key.decode())
                    self._validate_int_fields(key.decode(), torrent,
                                              [b'downloaded', b'uploaded', b'snatches',
                                               b'announces', b'seeders',
                                               b'leechers'], update=delete)
                else:
                    old_keys_2.append(key)
        for key in old_keys_2:
            print(key)
            if delete:
                self._redis.delete(key)

    def _validate_int_fields(self, key, data, hash_keys, update=False):
        # Nothing should be this large yet, even if not max int size
        max_int = 2 ** 62
        for hash_key in hash_keys:
            reset = False
            try:
                v = int(data[hash_key])
            except KeyError:
                print("[{}] No hash key: {}".format(key, hash_key))
                reset = True
            else:
                if v < 0:
                    print("[{}] Negative int: {}".format(hash_key))
                    reset = True
                elif v > max_int:
                    print("[{}] Max int: {}".format(hash_key, v))
                    reset = True
            if reset:
                self._redis.hset(key, hash_key, 0)
