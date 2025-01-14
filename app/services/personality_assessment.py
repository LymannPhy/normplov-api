import pandas as pd
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from app.models import AssessmentType
from app.models.user_response import UserResponse
from app.models.user_assessment_score import UserAssessmentScore
from app.models.dimension import Dimension
from app.models.personality_type import PersonalityType
from app.models.personality_trait import PersonalityTrait
from app.models.personality_strength import PersonalityStrength
from app.models.personality_weakness import PersonalityWeakness
from app.models.career import Career
from app.services.test import create_user_test
from app.schemas.personality_assessment import (
    PersonalityAssessmentResponse,
    PersonalityTypeDetails,
    DimensionScore,
    PersonalityTraits,
)
from ml_models.model_loader import load_personality_models
import logging
import json

logger = logging.getLogger(__name__)
dimension_models, personality_predictor, label_encoder = load_personality_models()


async def get_assessment_type_id(name: str, db: AsyncSession) -> int:
    stmt = select(AssessmentType.id).where(AssessmentType.name == name)
    result = await db.execute(stmt)
    assessment_type_id = result.scalars().first()
    if not assessment_type_id:
        raise HTTPException(status_code=404, detail=f"Assessment type '{name}' not found.")
    return assessment_type_id


async def process_personality_assessment(
    input_data: dict,
    db: AsyncSession,
    current_user,
) -> PersonalityAssessmentResponse:

    try:
        user_test = await create_user_test(db, current_user.id, "Personality")

        assessment_type_id = await get_assessment_type_id("Personality", db)

        # Calculate dimension scores
        input_responses_df = pd.DataFrame([input_data])
        dimension_scores = {}
        for dimension, model in dimension_models.items():
            prediction = model.predict(input_responses_df)[0]
            dimension_scores[dimension] = prediction

        total_score = sum(dimension_scores.values())
        normalized_scores = {
            dim: {
                "score": round(score, 2),
                "percentage": round((score / total_score) * 100, 2)
            }
            for dim, score in dimension_scores.items()
        }

        # Predict personality type
        input_data_for_prediction = pd.DataFrame([dimension_scores])
        predicted_class = personality_predictor.predict(input_data_for_prediction)
        predicted_personality = label_encoder.inverse_transform(predicted_class)[0]

        personality_query = select(PersonalityType).where(PersonalityType.name == predicted_personality)
        result = await db.execute(personality_query)
        personality_details = result.scalars().first()

        if not personality_details:
            raise HTTPException(status_code=400, detail="Personality details not found for the predicted class.")

        # Save assessment scores
        assessment_scores = []
        for dimension_name, score_data in normalized_scores.items():
            dimension_query = select(Dimension).where(Dimension.name == dimension_name)
            result = await db.execute(dimension_query)
            dimension = result.scalars().first()

            if not dimension:
                logger.warning(f"Dimension not found for {dimension_name}. Skipping.")
                continue

            assessment_scores.append(
                UserAssessmentScore(
                    uuid=str(uuid.uuid4()),
                    user_id=current_user.id,
                    user_test_id=user_test.id,
                    assessment_type_id=assessment_type_id,
                    dimension_id=dimension.id,
                    score=score_data,
                    created_at=datetime.utcnow(),
                )
            )

        if not assessment_scores:
            raise HTTPException(
                status_code=500,
                detail="Failed to resolve dimension IDs for personality assessment scores.",
            )

        db.add_all(assessment_scores)

        # Fetch personality traits
        traits_query = select(PersonalityTrait).where(PersonalityTrait.personality_type_id == personality_details.id)
        traits_result = await db.execute(traits_query)
        traits = traits_result.scalars().all()
        positive_traits = [trait.trait for trait in traits if trait.is_positive]
        negative_traits = [trait.trait for trait in traits if not trait.is_positive]

        # Fetch strengths and weaknesses
        strengths_query = select(PersonalityStrength).where(PersonalityStrength.personality_type_id == personality_details.id)
        strengths_result = await db.execute(strengths_query)
        strengths = [s.strength for s in strengths_result.scalars().all()]

        weaknesses_query = select(PersonalityWeakness).where(PersonalityWeakness.personality_type_id == personality_details.id)
        weaknesses_result = await db.execute(weaknesses_query)
        weaknesses = [w.weakness for w in weaknesses_result.scalars().all()]

        # Fetch careers from career table
        career_query = select(Career).where(Career.holland_code_id == personality_details.id)
        career_result = await db.execute(career_query)
        careers = [career.name for career in career_result.scalars().all()]

        # Construct the response
        response = PersonalityAssessmentResponse(
            user_uuid=current_user.uuid,
            personality_type=PersonalityTypeDetails(
                name=personality_details.name,
                title=personality_details.title,
                description=personality_details.description,
            ),
            dimensions=[
                DimensionScore(
                    dimension_name=dim,
                    score=data["score"],
                    percentage=f"{data['percentage']}%"
                )
                for dim, data in normalized_scores.items()
            ],
            traits=PersonalityTraits(positive=positive_traits, negative=negative_traits),
            strengths=strengths,
            weaknesses=weaknesses,
            career_recommendations=careers,
        )

        # Save user response
        user_response = UserResponse(
            uuid=str(uuid.uuid4()),
            user_id=current_user.id,
            user_test_id=user_test.id,
            assessment_type_id=assessment_type_id,
            response_data=json.dumps(response.dict()),
            created_at=datetime.utcnow(),
        )
        db.add(user_response)

        await db.commit()

        return response

    except Exception as e:
        logger.exception("An error occurred during personality assessment.")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
