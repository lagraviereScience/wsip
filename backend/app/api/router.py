from fastapi import APIRouter

from app.api.routes import auth, catalogue, feedback, health, me, privacy, recommendations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(catalogue.router)
api_router.include_router(recommendations.router)
api_router.include_router(feedback.router)
api_router.include_router(privacy.router)
