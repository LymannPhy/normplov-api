from fastapi import FastAPI
from app.api.v1.endpoints import auth, user, assessment, ai_recommendation
from app.core.database import engine, Base, get_db
from app.core.init import init_roles_and_admin
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async for db in get_db():
        await init_roles_and_admin(db)
        break

    yield

app = FastAPI(lifespan=lifespan)


app.include_router(auth.auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(user.user_router, prefix="/api/v1", tags=["user"])
app.include_router(assessment.assessment_router, prefix="/api/v1", tags=["assessment"])
app.include_router(ai_recommendation.ai_recommendation_router, prefix="/api/v1", tags=["ai_recommendations"])
