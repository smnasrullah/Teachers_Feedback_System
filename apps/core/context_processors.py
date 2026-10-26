def csp_nonce(request):
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
