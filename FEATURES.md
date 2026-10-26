# Wardrobe

A personal digital closet. Photograph the clothes you own, build outfits from them, plan your week, and pack for trips. It runs as a website and works in a phone or iPad browser.

## Features

**Pieces**
- Add clothing and accessories with a photo, name, category, colour, season, brand, price, tags and a 1-5 formality rating.
- Search and filter by category, season, status (in wardrobe, laundry, stored, donated) or text.
- Each piece shows how often it has been worn and its cost per wear.

**Cut-outs**
- When you add a piece, the app also makes a version with the background removed and lets you choose the original or the cut-out. You can switch any time, and make a cut-out later for older pieces.
- Works on photos of a single item and on photos of you wearing it (it removes the background and your skin). Where an arm or hand covered a worn piece, the gap is filled in by estimating the fabric around it, so that part is approximate.
- Runs on your own computer with free models.

**Outfits**
- Pick pieces and save them as an outfit with an occasion (everyday, work, evening, special, travel, active).
- Log "wore this" on any date to keep a wear history.
- "Surprise me" picks a random saved outfit.

**Style me**
- Suggests six fresh looks from pieces you already own.
- Matches colours, avoids clashing ones, and respects season and dress code.
- Rule-based, with no paid AI. One click saves a look as an outfit.

**Week planner**
- Seven-day view where you choose an outfit for each day.
- Enter your city to see each day's forecast (temperature range, conditions, rain chance).

**Trips**
- Create a trip with a destination and dates, choose the pieces to bring, and tick them off as you pack.
- Shows a day-by-day forecast for the destination and short packing tips.

**Fit check**
- Upload a photo of yourself in an outfit. It finds each piece (tee, watch, shoes, accessories), crops them out and lets you review and rename before adding them to your wardrobe.
- Runs on your own computer with a free open model. Photos are not uploaded anywhere, and only the cropped pieces are saved.
- Known limits: crops are rectangles, it can't read brand names, and it sometimes names things wrongly or finds extras. You review everything before it's saved.

## Beta features
Switched on only for admins and a few named users (see `WARDROBE_FEATURES` in settings).

**Perfumes**
- A separate shelf for fragrances: name, brand, bottle photo, concentration, scent family, notes, best season and occasion, size, price, a 0-5 rating and a status (in use, wishlist, finished).
- Search and filter by name, brand, note, family, season or status. Private to each account.

**Try on**
- Upload a full-body photo and see an outfit on you. Runs on your own computer with CatVTON and takes about 5 minutes per garment. Fine details can change.

## Accounts
Sign up and sign in with a username and password. Each account has its own private wardrobe: pieces, outfits, plans, trips and photos are only visible to their owner. New wardrobes can start empty or with a few sample pieces.

## Look and feel
Beige and royal-blue design with gold details and elegant serif headings. Layout adapts to desktop, tablet and phone.

## Sharing
`./share.sh` makes a public link from your computer using a free ngrok tunnel. Creating an account on the shared link needs an invite code, and the link only works while your computer is on and the script is running.

## Not included yet
- Brand reading from photos.
- Always-on hosting (needs a paid server for Fit check).
