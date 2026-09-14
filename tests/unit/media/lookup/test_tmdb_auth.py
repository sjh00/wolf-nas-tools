from unittest.mock import MagicMock

from app.infrastructure.external.tmdbv3api.tmdb import TMDb, is_tmdb_read_access_token


def test_detects_read_access_token():
    assert is_tmdb_read_access_token("eyJhbGciOiJIUzI1NiJ9.payload.sig") is True
    assert is_tmdb_read_access_token("  eyJhbGciOiJIUzI1NiJ9.payload.sig  ") is True


def test_detects_v3_api_key():
    assert is_tmdb_read_access_token("0123456789abcdef0123456789abcdef") is False
    assert is_tmdb_read_access_token("") is False
    assert is_tmdb_read_access_token("eyJ-not-a-jwt") is False


def test_call_uses_query_api_key_for_v3_key():
    tmdb = TMDb(session=MagicMock())
    tmdb.api_key = "0123456789abcdef0123456789abcdef"
    tmdb.domain = "https://api.themoviedb.org/3"
    tmdb.language = "zh"
    resp = MagicMock()
    resp.headers = {}
    resp.json.return_value = {"id": 11}
    tmdb._session.request.return_value = resp

    tmdb._call("/movie/11", "")

    url = tmdb._session.request.call_args[0][1]
    kwargs = tmdb._session.request.call_args.kwargs
    assert "api_key=0123456789abcdef0123456789abcdef" in url
    assert "Authorization" not in (kwargs.get("headers") or {})


def test_call_uses_bearer_for_read_access_token():
    token = "eyJhbGciOiJIUzI1NiJ9.payload.sig"
    tmdb = TMDb(session=MagicMock())
    tmdb.api_key = token
    tmdb.domain = "https://api.themoviedb.org/3"
    tmdb.language = "zh"
    resp = MagicMock()
    resp.headers = {}
    resp.json.return_value = {"id": 11}
    tmdb._session.request.return_value = resp

    tmdb._call("/movie/11", "")

    url = tmdb._session.request.call_args[0][1]
    kwargs = tmdb._session.request.call_args.kwargs
    assert "api_key=" not in url
    assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
    assert url.startswith("https://api.themoviedb.org/3/movie/11?")
