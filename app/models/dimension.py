from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class Dimension(Base):
    __tablename__ = "dimensions"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, nullable=False)
    name = Column(String(100), unique=True, nullable=False)
    assessment_type_id = Column(Integer, ForeignKey("assessment_types.id", ondelete="CASCADE"), nullable=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=None, onupdate=datetime.utcnow)

    # Use lazy import to avoid circular import
    assessment_type = relationship("AssessmentType", back_populates="dimensions")
    scores = relationship("UserAssessmentScore", back_populates="dimension", cascade="all, delete-orphan")