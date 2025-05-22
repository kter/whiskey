from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

# Create your models here.

class Whiskey(models.Model):
    name = models.CharField(max_length=200)
    distillery = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.distillery})"

class Review(models.Model):
    class ServingStyle(models.TextChoices):
        NEAT = 'NEAT', 'Neat'
        ON_THE_ROCKS = 'ROCKS', 'On the Rocks'
        WATER = 'WATER', 'With Water'
        SODA = 'SODA', 'With Soda'
        COCKTAIL = 'COCKTAIL', 'Cocktail'

    whiskey = models.ForeignKey(Whiskey, on_delete=models.CASCADE, related_name='reviews')
    user_id = models.CharField(max_length=200)  # Cognito User ID
    notes = models.TextField()
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    serving_style = models.CharField(max_length=10, choices=ServingStyle.choices)
    date = models.DateField()
    image_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user_id']),
            models.Index(fields=['date']),
        ]
        ordering = ['-date']

    def __str__(self):
        return f"Review of {self.whiskey.name} by {self.user_id}"
