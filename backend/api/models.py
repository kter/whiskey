from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

@dataclass
class Whiskey:
    id: str
    name: str
    distillery: str
    created_at: str
    updated_at: str
    avg_rating: Optional[float] = None
    review_count: Optional[int] = None

@dataclass
class User:
    user_id: str
    nickname: str
    display_name: Optional[str]
    created_at: str
    updated_at: str

@dataclass
class Review:
    id: str
    whiskey_id: str
    user_id: str
    notes: str
    rating: int
    serving_style: str
    date: str
    created_at: str
    updated_at: str
    image_url: Optional[str] = None
    
    # レガシーコードとの互換性のためのサービングスタイル定義
    class ServingStyle:
        NEAT = 'NEAT'
        ON_THE_ROCKS = 'ROCKS' 
        WATER = 'WATER'
        SODA = 'SODA'
        COCKTAIL = 'COCKTAIL'
        
        CHOICES = [
            (NEAT, 'Neat'),
            (ON_THE_ROCKS, 'On the Rocks'),
            (WATER, 'With Water'),
            (SODA, 'With Soda'),
            (COCKTAIL, 'Cocktail'),
        ]
