# Whiskey Log

Whiskey Log is a photo-first tasting journal. It turns uploaded drink photos into records that remain useful even when automated recognition is uncertain.

## Language

**Drink Log**:
A user's record of one drink, including its photo, whiskey name, serving style, place, and time.
_Avoid_: Tasting entry, record

**Recording Session**:
The temporary collection of drink photos a user is preparing and confirming together before their Drink Logs are saved.
_Avoid_: Batch, upload queue

**Analysis Result**:
A time-limited reading of one uploaded photo, bound to that photo and user, containing Whiskey Candidates and a suggested serving style.
_Avoid_: AI result, prediction

**Completion**:
The confirmed fields staged for a pending Drink Log and applied when its photo is finalised.
_Avoid_: Finalisation payload, pending data

**Whiskey Candidate**:
One possible whiskey read from a photo. It may be linked to the whiskey catalog or remain an unconfirmed reading for the user to correct.
_Avoid_: Match, detection

**Usage Budget**:
The per-user or global allowance that limits costly operations and retained images so the application's spending remains bounded.
_Avoid_: Rate limit, quota

**Place**:
The bar, shop, or other location where a Drink Log was made, represented by user-entered store information and an optional Place ID.
_Avoid_: DrinkLogStore, venue record

**Tombstone**:
A `deleting` Drink Log record created by the reconciler for an orphan image with no record, so that image deletion uses the same conditional-write exclusion as the create path.
_Avoid_: Lifecycle status, deleted record

## Drink Log lifecycle

A Drink Log starts `pending`, becomes `complete` when its image and Completion are finalised, and moves to `deleting` for recoverable deletion. The reconciler also creates a Tombstone as a `deleting` record for an orphan image, then removes the image and record through that same flow.
