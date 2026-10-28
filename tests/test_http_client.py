"""Tests for response decoding in the HTTP client."""

from __future__ import annotations

import json

import requests

from rpa_jobs.http_client import HttpClient


def make_response(body: bytes, content_type: str) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = body
    response.headers["Content-Type"] = content_type
    return response


def test_json_without_charset_is_decoded_as_utf8():
    payload = {"company": "Sotheby’s", "note": "We’ve been – here"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response = make_response(body, "application/json")

    text = HttpClient._decode(response)

    assert "Sotheby’s" in text
    assert "We’ve been – here" in text
    assert "â" not in text


def test_xml_without_charset_is_decoded_as_utf8():
    body = "<?xml version='1.0'?><rss><title>Café – Remote</title></rss>".encode("utf-8")
    response = make_response(body, "application/rss+xml")

    assert "Café – Remote" in HttpClient._decode(response)


def test_structured_body_detected_with_vague_content_type():
    body = '{"title": "Développeur – Paris"}'.encode("utf-8")
    response = make_response(body, "text/plain")

    assert "Développeur – Paris" in HttpClient._decode(response)


def test_explicit_charset_is_respected():
    body = "Café".encode("iso-8859-1")
    response = make_response(body, "text/plain; charset=iso-8859-1")

    assert HttpClient._decode(response) == "Café"


def test_utf8_bom_is_stripped():
    body = "\ufeff{\"title\": \"Engineer\"}".encode("utf-8")
    response = make_response(body, "application/json")

    assert HttpClient._decode(response).startswith("{")


def test_html_meta_charset_is_honoured():
    body = (
        '<html><head><meta charset="utf-8"></head><body>Café</body></html>'
    ).encode("utf-8")
    response = make_response(body, "text/html")

    assert "Café" in HttpClient._decode(response)


def test_html_uses_apparent_encoding_when_nothing_declared():
    body = "<html><body>" + ("Plain ASCII text. " * 40) + "</body></html>"
    response = make_response(body.encode("ascii"), "text/html")

    assert "Plain ASCII text." in HttpClient._decode(response)
