import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from datetime import datetime
from app.models import AssessmentType
from app.models.user_feedback import UserFeedback
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


async def get_promoted_feedbacks(db: AsyncSession) -> list:
    try:
        stmt = (
            select(UserFeedback)
            .options(joinedload(UserFeedback.user))
            .where(UserFeedback.is_promoted == True, UserFeedback.is_deleted == False)
        )
        result = await db.execute(stmt)
        feedbacks = result.scalars().all()

        return [
            {
                "feedback_uuid": str(feedback.uuid),
                "username": feedback.user.username,
                "email": feedback.user.email,
                "avatar": feedback.user.avatar,
                "feedback": feedback.feedback,
                "created_at": feedback.created_at.strftime("%d-%B-%Y"),
            }
            for feedback in feedbacks
        ]
    except Exception as e:
        logger.exception("Error fetching promoted feedbacks")
        raise HTTPException(status_code=500, detail="Failed to fetch promoted feedbacks")


async def get_all_feedbacks(db: AsyncSession) -> list:
    try:
        stmt = (
            select(UserFeedback)
            .options(joinedload(UserFeedback.user))
            .where(UserFeedback.is_deleted == False)
        )
        result = await db.execute(stmt)
        feedbacks = result.scalars().all()

        return [
            {
                "feedback_uuid": str(feedback.uuid),
                "username": feedback.user.username,
                "email": feedback.user.email,
                "avatar": feedback.user.avatar,
                "feedback": feedback.feedback,
                "created_at": feedback.created_at.strftime("%d-%B-%Y"),
                "is_deleted": feedback.is_deleted,
                "is_promoted": feedback.is_promoted,
            }
            for feedback in feedbacks
        ]
    except Exception as e:
        logger.exception("Error fetching feedbacks")
        raise HTTPException(status_code=500, detail="Failed to fetch feedbacks")


async def promote_feedback(feedback_uuid: str, db: AsyncSession) -> None:

    try:
        stmt = select(UserFeedback).where(
            UserFeedback.uuid == feedback_uuid,
            UserFeedback.is_deleted == False
        )
        result = await db.execute(stmt)
        feedback = result.scalars().first()

        if not feedback:
            raise HTTPException(status_code=404, detail="Feedback not found")

        # Here I just change the status of the feedback
        feedback.is_promoted = True
        feedback.updated_at = datetime.utcnow()

        await db.commit()

    except Exception as e:
        logger.exception("Error promoting feedback")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to promote feedback")


async def create_feedback(feedback: str, assessment_type_uuid: str, current_user, db: AsyncSession) -> str:

    try:
        result = await db.execute(
            select(AssessmentType.id).where(
                AssessmentType.uuid == str(uuid.UUID(assessment_type_uuid)),
                AssessmentType.is_deleted == False,
            )
        )
        assessment_type_id = result.scalars().first()

        if not assessment_type_id:
            raise HTTPException(status_code=404, detail="Assessment type not found")

        feedback_uuid = str(uuid.uuid4())
        new_feedback = UserFeedback(
            uuid=feedback_uuid,
            user_id=current_user.id,
            assessment_type_id=assessment_type_id,
            feedback=feedback,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(new_feedback)
        await db.commit()

        return feedback_uuid

    except ValueError:
        logger.error("Invalid UUID format for assessment type")
        raise HTTPException(status_code=400, detail="Invalid assessment type UUID format")
    except IntegrityError:
        logger.error("Database integrity error while creating feedback")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error occurred")
    except Exception as e:
        logger.exception("Error creating feedback")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create feedback")