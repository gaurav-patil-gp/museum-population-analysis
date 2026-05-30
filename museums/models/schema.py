"""SQLAlchemy ORM models for the museums database."""

from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class City(Base):
    """A city that hosts one or more museums."""

    __tablename__ = "city"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    population: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Wikidata entity ID, e.g. "Q90" for Paris. Used to trace the population source.
    wikidata_qid: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)

    museums: Mapped[list["Museum"]] = relationship("Museum", back_populates="city")

    def __repr__(self) -> str:
        return f"<City name={self.name!r} country={self.country!r}>"


class Museum(Base):
    """A museum with more than 2,000,000 annual visitors."""

    __tablename__ = "museum"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("city.id"), nullable=False)
    annual_visitors: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # The year the visitor count was reported (extracted from the Wikipedia table).
    visitor_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    museum_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    wikipedia_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    city: Mapped[City] = relationship("City", back_populates="museums")

    def __repr__(self) -> str:
        return f"<Museum name={self.name!r} visitors={self.annual_visitors}>"
