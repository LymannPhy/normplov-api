import pandas as pd
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from app.models.user_response import UserResponse
from app.models.user_assessment_score import UserAssessmentScore
from app.models.dimension import Dimension
from app.models.holland_code import HollandCode
from app.models.holland_key_trait import HollandKeyTrait
from app.models.career import Career
from app.models.assessment_type import AssessmentType
from app.services.test import create_user_test
from app.schemas.interest_assessment import InterestAssessmentResponse, ChartData, DimensionDescription
from ml_models.model_loader import load_interest_models
import logging
import json

logger = logging.getLogger(__name__)
class_model, prob_model, label_encoder = load_interest_models()


async def get_assessment_type_id(name: str, db: AsyncSession) -> int:
    stmt = select(AssessmentType.id).where(AssessmentType.name == name)
    result = await db.execute(stmt)
    assessment_type_id = result.scalars().first()
    if not assessment_type_id:
        raise HTTPException(status_code=404, detail=f"Assessment type '{name}' not found.")
    return assessment_type_id


async def process_interest_assessment(
    responses: dict,
    db: AsyncSession,
    current_user,
) -> InterestAssessmentResponse:

    try:
        user_test = await create_user_test(db, current_user.id, "Interest")

        assessment_type_id = await get_assessment_type_id("Interests", db)

        # Predict scores and class
        input_data = pd.DataFrame([responses])
        input_data_prob = input_data.reindex(columns=prob_model.feature_names_in_, fill_value=0)
        prob_predictions = prob_model.predict(input_data_prob)

        prob_scores = pd.DataFrame(
            prob_predictions,
            columns=["R_Score", "I_Score", "A_Score", "S_Score", "E_Score", "C_Score"],
        )

        input_data_class = input_data.reindex(columns=class_model.feature_names_in_, fill_value=0)
        class_predictions = class_model.predict(input_data_class)
        predicted_class = label_encoder.inverse_transform(class_predictions)[0]

        # Fetch Holland Code and Key Traits
        holland_code_query = select(HollandCode).where(HollandCode.code == predicted_class)
        result = await db.execute(holland_code_query)
        holland_code = result.scalars().first()

        if not holland_code:
            raise HTTPException(status_code=400, detail="Holland code not found for the predicted class.")

        key_traits_query = select(HollandKeyTrait).where(HollandKeyTrait.holland_code_id == holland_code.id)
        key_traits_result = await db.execute(key_traits_query)
        key_traits = [trait.key_trait for trait in key_traits_result.scalars().all()]

        # Fetch Career Paths from Career Table
        career_query = select(Career).where(Career.holland_code_id == holland_code.id)
        career_result = await db.execute(career_query)
        career_paths = [career.name for career in career_result.scalars().all()]

        # Mapping Scores to Dimensions
        key_to_dimension = {
            "R_Score": "Realistic",
            "I_Score": "Investigative",
            "A_Score": "Artistic",
            "S_Score": "Social",
            "E_Score": "Enterprising",
            "C_Score": "Conventional",
        }

        chart_data = []
        dimension_descriptions = []
        assessment_scores = []

        for score_key, score_value in prob_scores.iloc[0].items():
            dimension_name = key_to_dimension.get(score_key)
            if not dimension_name:
                logger.warning(f"Unmapped score key: {score_key}. Skipping.")
                continue

            dimension_query = select(Dimension).where(Dimension.name == dimension_name)
            result = await db.execute(dimension_query)
            dimension = result.scalars().first()

            if not dimension:
                logger.error(f"Dimension not found for {dimension_name}. Skipping.")
                continue

            chart_data.append(ChartData(label=dimension_name, score=round(score_value, 2)))
            dimension_descriptions.append({
                "dimension_name": dimension.name,
                "description": dimension.description,
                "score": score_value,
            })

            percentage = round((score_value / prob_scores.iloc[0].sum()) * 100, 2)
            assessment_scores.append(
                UserAssessmentScore(
                    uuid=str(uuid.uuid4()),
                    user_id=current_user.id,
                    user_test_id=user_test.id,
                    assessment_type_id=assessment_type_id,
                    dimension_id=dimension.id,
                    score={
                        "score": round(score_value, 2),
                        "percentage": percentage,
                    },
                    created_at=datetime.utcnow(),
                )
            )

        if not assessment_scores:
            logger.error("No assessment scores to save.")
            raise HTTPException(
                status_code=500,
                detail="Failed to resolve dimension IDs for interest assessment scores.",
            )

        db.add_all(assessment_scores)

        top_dimensions = sorted(dimension_descriptions, key=lambda x: x["score"], reverse=True)[:2]

        response = InterestAssessmentResponse(
            user_id=current_user.uuid,
            holland_code=holland_code.code,
            type_name=holland_code.type,
            description=holland_code.description,
            key_traits=key_traits,
            career_path=career_paths,
            chart_data=chart_data,
            dimension_descriptions=[
                DimensionDescription(
                    dimension_name=dim["dimension_name"],
                    description=dim["description"],
                )
                for dim in top_dimensions
            ],
        )

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
        logger.exception("An error occurred during interest assessment.")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
