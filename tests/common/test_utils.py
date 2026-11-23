import uuid
from decimal import Decimal

import pytest
from django.db import models
from rest_framework import exceptions, serializers
from rest_framework.views import APIView

from apps.common.exceptions import api_exception_handler
from apps.common.models import BaseModel
from apps.common.money import format_tzs, round_money, to_money
from apps.common.pagination import StandardPagination
from apps.common.phone import InvalidPhoneNumber, normalize_phone

# --- BaseModel -------------------------------------------------------------


class TestBaseModel:
    def test_is_abstract(self):
        assert BaseModel._meta.abstract is True

    def test_uuid_primary_key(self):
        field = BaseModel._meta.get_field("id")
        assert isinstance(field, models.UUIDField)
        assert field.primary_key is True
        assert field.default is uuid.uuid4
        assert field.editable is False

    def test_timestamps(self):
        created = BaseModel._meta.get_field("created_at")
        updated = BaseModel._meta.get_field("updated_at")
        assert created.auto_now_add is True
        assert updated.auto_now is True


# --- Money -----------------------------------------------------------------


class TestMoney:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("1.005"), Decimal("1.01")),  # half-up, not banker's
            (Decimal("1.015"), Decimal("1.02")),
            (Decimal("2.5"), Decimal("2.50")),
            (Decimal("1500.004"), Decimal("1500.00")),
            (Decimal("-1.005"), Decimal("-1.01")),
            ("15000", Decimal("15000.00")),
            (15000, Decimal("15000.00")),
        ],
    )
    def test_round_money_half_up(self, value, expected):
        result = round_money(value)
        assert result == expected
        assert result.as_tuple().exponent == -2

    def test_round_money_rejects_float(self):
        with pytest.raises(TypeError):
            round_money(1.005)

    def test_to_money_parses_strings(self):
        assert to_money("15000.50") == Decimal("15000.50")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("15000"), "TZS 15,000"),
            (Decimal("15000.00"), "TZS 15,000"),
            (Decimal("1234567.5"), "TZS 1,234,567.50"),
            (Decimal("0"), "TZS 0"),
            (Decimal("999.999"), "TZS 1,000"),
        ],
    )
    def test_format_tzs(self, value, expected):
        assert format_tzs(value) == expected


# --- Phone -----------------------------------------------------------------


class TestPhone:
    @pytest.mark.parametrize(
        "raw",
        [
            "0712345678",
            "712345678",
            "255712345678",
            "+255712345678",
            "+255 712 345 678",
            "+255-712-345-678",
            " 0712 345 678 ",
        ],
    )
    def test_normalizes_tanzanian_numbers_to_e164(self, raw):
        assert normalize_phone(raw) == "+255712345678"

    def test_accepts_6x_prefix(self):
        assert normalize_phone("0621234567") == "+255621234567"

    def test_keeps_other_international_numbers(self):
        assert normalize_phone("+254712345678") == "+254712345678"

    @pytest.mark.parametrize(
        "raw",
        ["", "abc", "12345", "07123456789", "0212345678", "+12", "+2557123", "++255712345678"],
    )
    def test_rejects_invalid(self, raw):
        with pytest.raises(InvalidPhoneNumber):
            normalize_phone(raw)

    def test_invalid_phone_is_value_error(self):
        assert issubclass(InvalidPhoneNumber, ValueError)


# --- Exception handler -----------------------------------------------------


def _context():
    return {"view": APIView(), "request": None}


class TestExceptionHandler:
    def test_validation_error_shape(self):
        exc = serializers.ValidationError({"phone": ["Invalid phone."]})
        response = api_exception_handler(exc, _context())
        assert response.status_code == 400
        assert response.data == {
            "detail": "Invalid input.",
            "code": "invalid",
            "errors": {"phone": ["Invalid phone."]},
        }

    def test_non_field_validation_error(self):
        exc = serializers.ValidationError(["Something is wrong."])
        response = api_exception_handler(exc, _context())
        assert response.data["errors"] == {"non_field_errors": ["Something is wrong."]}

    def test_not_authenticated_shape(self):
        response = api_exception_handler(exceptions.NotAuthenticated(), _context())
        assert response.status_code == 401
        assert response.data["code"] == "not_authenticated"
        assert response.data["errors"] == {}
        assert response.data["detail"]

    def test_permission_denied_shape(self):
        response = api_exception_handler(exceptions.PermissionDenied(), _context())
        assert response.status_code == 403
        assert response.data["code"] == "permission_denied"

    def test_django_404_is_mapped(self):
        from django.http import Http404

        response = api_exception_handler(Http404(), _context())
        assert response.status_code == 404
        assert response.data["code"] == "not_found"

    def test_unhandled_exception_returns_none(self):
        assert api_exception_handler(RuntimeError("boom"), _context()) is None


# --- Pagination ------------------------------------------------------------


class TestPagination:
    def test_page_size_settings(self):
        p = StandardPagination()
        assert p.page_size == 20
        assert p.page_size_query_param == "page_size"
        assert p.max_page_size == 100
