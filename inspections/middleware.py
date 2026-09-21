from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin


class DomainValidationMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if isinstance(exception, ValidationError):
            return render(request, 'inspections/conflict.html', {'errors': exception.messages}, status=409)
        return None
