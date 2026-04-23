from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Rate limiter with NO default_limits — limits are declared explicitly per-route
# via @limiter.limit(). Using both global default_limits AND per-route decorators
# would apply the same limit twice, causing inconsistent behaviour.
limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiting(app):
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
