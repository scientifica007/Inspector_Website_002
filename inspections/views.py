from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

@login_required
def dashboard(request):
    return HttpResponse('منصة التفتيش — جاري إعداد مساحة العمل')
