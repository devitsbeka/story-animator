# Hero Character Shortlist: purchasable stylized young man for a code-driven Blender 4.2 series

Researched 2026-11-21 by web search and listing fetches. Nothing was bought and no accounts were created.

**Pipeline target:** Blender 4.2 LTS with Cycles, everything driven by bpy. The character needs an IK body rig, ARKit-52 shape keys for our expression and eye engine, rotatable eyeballs, under 150k polys, and a commercial licence that covers monetized video.

> **Caveat:** No listing on the market meets every requirement: a Pixar-grade young man in a hoodie, joggers, sneakers and cap, with ARKit 52 and separate eyes confirmed. Every candidate below misses at least one item. Most listings do not state the poly count or the eye construction. Treat anything marked "unconfirmed" as a question for the seller before buying.
> Listing text is the seller's marketing copy. Prices are from the listing on the research date, in USD, before tax.

---

## Ranked top 8

### 1. Humanz Male: Rigged Modular Cartoon Character Pack (ThreeDee / Samuel Briskar)
- **Marketplaces and URLs:**
  - Fab, $23.99: https://www.fab.com/listings/ef438a3a-b1d9-46d1-b107-b6aaf1aec45b
  - Gumroad, males only, $48: https://threedeeshop.gumroad.com/l/humanz-male
  - Superhive, male and female, $69: https://superhivemarket.com/products/humanz-modular-low-poly-human-characters
  - Maker page: https://www.threedee.design/products/3d-models/humanz/
- **Price:** $23.99 on Fab, $48 on Gumroad (males only), $69 on Superhive (both sexes).
- **Licence:** Fab Standard (commercial use, any media) or Superhive "Royalty Free". ThreeDee's own licence (https://www.threedee.design/license/) says "Rendered images and video fit Standard": monetized video is OK, with no royalties and no credit required. You may not redistribute the asset files or ship extractable GLBs, and AI training is not allowed.
- **Rig:** Rigify body and face rigs, with 40 premade poses.
- **Blendshape evidence:** Fab says "52 ARKit blendshapes, facial expressions, and lipsync mouth shapes". Superhive says "Use the included 52 ARKit blendshapes to build facial performances."
  - The listings name all 52, which covers eyeBlink, eyeWide, eyeSquint, the brow shapes, jawOpen, mouthSmile and mouthFrown.
  - Visemes come as separate "lipsync mouth shapes".
  - Individual shape-key names are not published, so check that they use exact ARKit spelling.
- **Eyes:** "Multiple eye types and variations included". Separate rotatable eyeball meshes are likely for this maker's cartoon style but not stated (unconfirmed).
- **Formats:** .blend, FBX, GLB, OBJ+MTL, and PBR textures.
- **Poly count:** Not stated ("low-polygon quad mesh", "optimized vertex count"). Very likely well under 150k.
- **Wardrobe:** Modular outfits, tops, bottoms, shoes, hair and accessories, sold as casual and sporty looks. Hoodie, cap, sneakers and joggers are not named explicitly (unconfirmed).
- **Style fit: 7/10.** Appealing, clean, toy-like cartoon proportions, and modular, so we can art-direct one fixed hero. It is closer to a polished explainer or advert look than to Pixar hero detail: simple skin shading and low-poly.
- **Risks:**
  - **Blender version conflict.** Fab says "Blender 5.0 or newer" and Superhive says "4.0 to 5.2". A 5.x .blend may not open cleanly in 4.2. Fallback: use the FBX or GLB, which keep the shape keys but lose the Rigify controls, then re-rig.
  - Low-poly look may need subdivision and shader upgrades for Cycles close-ups.
  - Garment list unverified.

### 2. University Student (ThreeDee)
- **Marketplace and URL:** ThreeDee direct, checkout on Gumroad, $88: https://www.threedee.design/products/3d-models/university-student/
- **Price:** $88.
- **Licence:** ThreeDee Standard Commercial, the same terms as #1. Monetized video OK.
- **Rig:** Full body and face rig built with "Autorig 2.0", i.e. Auto-Rig Pro 2.0. Animating an ARP rig does not require the add-on, but ARP-specific tools do.
- **Blendshape evidence:** "52 ARKit blendshapes" plus a "Blender Expression panel" and a "Lipsync viseme panel".
- **Eyes:** Not stated (unconfirmed).
- **Formats:** .blend, FBX, OBJ, GLB.
- **Poly count:** Not stated ("low-poly quad mesh").
- **Wardrobe:** Fixed student outfit, not described on the page. Needs retexturing or modelling to get the hoodie and cap.
- **Style fit: 7/10.** The best age match in the ThreeDee range: a young adult, student archetype, and appealing.
- **Risks:**
  - Fixed outfit.
  - ARP rig rather than Rigify, so our IK and bpy code must target ARP bone names.
  - Blender version not stated.

### 3. Man Cartoon Character Rigged, "Disney/Pixar style" (ThreeDee)
- **Marketplaces and URLs:**
  - Fab, $23.99: https://www.fab.com/listings/3b4a8619-3ae3-4d36-8b01-9b1a1889262e
  - Superhive, $49 (was $70): https://superhivemarket.com/products/man-cartoon-character-rigged-in-blender
  - CGTrader (older Blender 3.0.1 version): https://www.cgtrader.com/3d-models/character/man/man-cartoon-character-rigged-in-blender
- **Price:** $23.99 on Fab, $49 on Superhive.
- **Licence:** Fab Standard or Superhive Royalty Free. Commercial video OK.
- **Rig:** Rigify full-body rig. Advanced face and body rig, with 20 to 24 premade poses in an Action Library.
- **Blendshape evidence:** Fab says "52 Arkit Blendshapes included", with lipsync and predefined expressions including "eyes blinking". Superhive says "The 52 ARKit blendshapes provide facial shapes for animation."
- **Eyes:** Not described (unconfirmed).
- **Formats:**
  - Fab lists Blender 4.2 (Cycles and EEVEE), FBX, GLB and OBJ. The highlights also say "made in Blender 4.1.1".
  - Superhive lists BLEND and FBX for Blender 4.0 to 5.2.
  - PBR materials.
- **Poly count:** Not stated ("low-poly, clean topology").
- **Wardrobe:** Fixed casual presenter outfit.
- **Style fit: 6/10.** Explicitly Disney/Pixar-inspired, but it is an adult "friendly presenter" (tags: dad, father, brother), not a 20-something hero.
- **Risks:** Reads older than our hero. Fixed outfit. Same low-poly finish as #1. **Lowest version risk:** the only listing explicitly built as a Blender 4.2 Cycles file.

### 4. Reallusion Character Creator 4/5 with a stylized toon pack and hoodie/cap clothing
- **Marketplace and URLs:** Reallusion Content Store. Candidate packs:
  - "The Dudes" (MAKARTOONS, 5 stylized men): https://www.reallusion.com/ContentStore/Character-Creator/Pack/3D-characters-The-Dudes/default.html
  - "Stylized Toon Family": https://reallusion.com/ContentStore/Character-Creator/Pack/3D-characters-Stylized-Toon-Family/default.html
  - CC5 product and pricing: https://www.reallusion.com/plan-and-pricing/individual/perpetual
- **Price:**
  - CC5 software: about $299 perpetual (Deluxe about $479–$499).
  - Toon pack: price not shown on the pages; typically $100–$250.
  - Total roughly $400–$650 (estimate).
- **Licence (flagged):** Reallusion's content policy (https://www.reallusion.com/license/content.html) says Standard allows you to "Export content to any external software or game engine", and its table lists "Render image or video for commercial use" as included. "Standard Licenses grant the use of characters with CC Components for all commercial imagery."
  - Extended is needed only for games, XR or interactive use.
  - **Monetized Blender-rendered video is OK under Standard, per the current policy.**
  - Older forum answers from Reallusion staff contradict this, and individual third-party packs can carry their own terms. Confirm in writing for the exact pack before buying.
- **Rig:** CC Base humanoid skeleton. The free CC Blender Tools add-on (github.com/soupday/cc_blender_tools) imports it and can generate a full Rigify rig, which retargets cleanly to Mixamo, UE or Unity.
- **Blendshape evidence:**
  - The CC4/CC5 Standard and Extended expression profiles (about 140 morphs) are a superset of ARKit 52: Eye_Blink_L/R, Eye_Wide, Eye_Squint, Brow_Raise_Inner/Outer, Brow_Drop, Jaw_Open, Mouth_Smile, Mouth_Frown and so on, plus visemes (V_Open, V_Explosive, V_Dental_Lip, V_Tight_O, V_Wide, V_Affricate and others).
  - CC is driven live by iPhone ARKit capture, which shows the mapping is complete.
  - **The names are CC-style, not ARKit-spelled.** We need a remap table, which is one dict in our engine.
  - Pack pages confirm only that facial profiles are "ready for Character Creator 4" with custom expressions. Exact morph availability on toon heads needs checking.
  - Expression wrinkle maps come into Blender through CC Blender Tools. They are less relevant for toon skin.
- **Eyes:** Yes, confirmed. Separate CC_Base_Eye meshes with occlusion and tear-line meshes, and eyelids are built to close fully.
- **Formats:** FBX export from CC, then CC Blender Tools import with PBR, SSS skin and Cycles shaders.
- **Poly count:** CC base is roughly 15k–30k quads before subdivision, plus clothing. Fits easily under 150k.
- **Wardrobe:** The CC clothing ecosystem has many hoodie, jogger, sneaker and cap items. Clothing auto-conforms to the body.
- **Style fit: 8/10.** The best facial system, eyes and skin quality for a Pixar-ish look, and the fully dressed hero is achievable. Toon packs are stylized-cartoon rather than strictly Pixar, but head morphs are tunable.
- **Risks:**
  - Most expensive option, and it needs a Windows or Mac CC licence in the loop.
  - Licence terms vary by pack and have changed historically.
  - CC's subtle "realistic" default look can creep toward uncanny if not pushed stylized.
  - Shape-key name remap needed.

### 5. Adventure Male 01: Stylized Character (Lab3 Studio)
- **Marketplace and URL:** Fab, $24.99: https://www.fab.com/listings/d285ee79-e3b3-4715-92c6-439e4db12a98
- **Price:** $24.99.
- **Licence:** Fab Standard. Commercial use in any media is allowed. The Personal and Professional tiers have the same rights; Professional applies only above $100k annual revenue.
- **Rig:** Based on the UE5 Quinn/Manny skeleton with 1:1 proportions, so it is Unreal-humanoid compatible and easy to retarget to Mixamo.
- **Blendshape evidence:** "The face has ARkit supported blendshapes and an example blinking animation." No count or list (the full 52 is unconfirmed).
- **Eyes:** Not stated.
- **Formats:** UE 5.6/5.7 project and "source .FBX files (with textures)". No .blend.
- **Poly count:** Not stated ("Lowpoly" tag).
- **Wardrobe:** 7 modular clothing items with colour variants, contemporary and action look. Lab3 male packs inter-merge.
- **Style fit: 5/10.** A stylized game character (Fortnite-like), appealing, but not Pixar film quality.
- **Risks:**
  - Unreal-first, so materials must be rebuilt for Cycles.
  - ARKit coverage unverified.
  - Hoodie and cap not confirmed.

### 6. Guy: A Stylized Rigged Character
- **Marketplace and URL:** Superhive, $7: https://superhivemarket.com/products/guy-a-stylized-rigged-character
- **Price:** $7.
- **Licence:** Superhive Royalty Free. Commercial video OK.
- **Rig:** "expertly rigged". Rig type not stated.
- **Blendshape evidence:** "all 52 ARKit blendshapes, plus additional facial expressions".
- **Eyes:** Not stated.
- **Formats:** Blender. Built for Blender 3.3–4.2, so 4.2 compatibility is explicit.
- **Poly count:** Not stated ("good typology for animation").
- **Wardrobe:** Not described (tag "3d-stylized-boy").
- **Style fit: 5/10.** Unknown quality. Cheap enough to buy as a test rig for wiring up the ARKit and eye engine.
- **Risks:** Sparse listing. Rig and topology quality unknown. Possibly younger than 20s.

### 7. Stylized Teen Boy 3D Character: Rigged & Animated (PixelMeshStudio)
- **Marketplace and URLs:**
  - Fab, $9.99: https://www.fab.com/listings/d3d671b3-615f-43e1-bb80-b3147714e2c2
  - Similar listing on Sketchfab, 92.3k tris: https://sketchfab.com/3d-models/stylized-cartoon-boy-3d-model-character-rigged-c94b7ba580f64762a1a01ed3c0763bc0
- **Price:** $9.99.
- **Licence:** Fab Standard. Commercial use OK.
- **Rig:** "Humanoid Rig". Idle, walk, run and talk animations.
- **Blendshape evidence:** **None.** The listing only says "Expressive Face". This fails the ARKit requirement. Shapes would have to be authored, for example with an ARKit shape-key generator add-on or by hand.
- **Eyes:** Not stated.
- **Formats:** FBX, GLB/GLTF, OBJ, USDZ. BLEND is claimed in the description but missing from the formats widget.
- **Poly count:** About 92k tris (Sketchfab twin).
- **Wardrobe:** **The best outfit match:** hoodie and vest, cargo pants, modern sneakers.
- **Style fit: 6/10.** Right vibe and outfit. Teen rather than 20s.
- **Risks:**
  - No face shapes.
  - Possibly AI-assisted (the listing says not, but it allows AI use).
  - Topology unknown.

### 8. Modern Guy 2 Oliver (FlugoLukss)
- **Marketplace and URL:** Fab, $20.99: https://www.fab.com/listings/5f2c6a3a-2c12-4b11-87f8-b2a39b52f6b5
- **Price:** $20.99.
- **Licence:** Fab Standard. Commercial use OK.
- **Rig:** Epic Skeleton UE4/UE5 with extra bones, including IK bones and separate eye bones "eye_r"/"eye_l".
- **Blendshape evidence:** "Arkit Apple Blendshapes … tested with Live Link Face". No count is given, but Live Link Face implies the 52.
- **Eyes:** Eye bones present, which implies separate rotatable eyes.
- **Formats:** Unreal Engine only. FBX has to be exported from UE.
- **Poly count:** Hoodie mesh alone is 90,916 tris and hair is 103,676 tris, which **exceeds the 150k budget**.
- **Wardrobe:** Hoodie confirmed. Street, K-pop look.
- **Style fit: 4/10.** Tagged both realistic and stylized: semi-real K-pop proportions, which risks the uncanny look we want to avoid.
- **Risks:** UE-only delivery, heavy polys, near-realistic style.

---

## Single best pick and runner-up

**Best pick: #1 Humanz Male (ThreeDee). $23.99 on Fab:** https://www.fab.com/listings/ef438a3a-b1d9-46d1-b107-b6aaf1aec45b
- It is the only candidate that combines all of these:
  - Confirmed ARKit 52 plus lipsync shapes.
  - A Rigify body and face rig, which is native to our bpy and IK code.
  - Clean quad low-poly mesh, with .blend, FBX and GLB formats.
  - A clear licence for monetized video.
  - A **modular wardrobe**, so the hoodie, joggers, sneakers and cap look can be assembled or kit-bashed.
- Before relying on it, check the .blend file version. If it was saved in Blender 5.x, either move the pipeline to Blender 4.5 or 5.x, or ask the seller for a 4.2 file. The Superhive listing claims 4.0–5.2 support.

**Runner-up: #4 Reallusion CC4/CC5 with a toon pack.**
- It has the best facial system and the only confirmed separate eyeballs, can be fully dressed in hoodie, joggers, sneakers and cap, and gets Cycles-ready SSS shading through CC Blender Tools.
- Choose it if we want higher fidelity than ThreeDee's low-poly look and can afford about $400–$650 plus a shape-key name remap.
- **Licence check:** Reallusion's current policy allows exporting to Blender and rendering commercial video under Standard. Get written confirmation for the specific pack.

**Budget fallback:** #3 Man Cartoon Character Rigged. $23.99 on Fab, and the only listing natively built as a Blender 4.2 Cycles file. Usable as a stand-in hero or a test rig, but it reads older than 20s.

---

## Excluded or flagged sources

| Source | Verdict |
|---|---|
| **Unity Asset Store** characters | **Flagged.** The Unity EULA restricts assets to Unity-based projects, so they are not OK for a Blender-rendered series. Excluded. |
| **Ready Player Me** | **Dead end.** Netflix acquired it in Dec 2025, and the public avatar services and APIs were scheduled to shut down on 31 Jan 2026 (TechCrunch, 2025-12-19). Avatars had ARKit shapes, but the service and licence are no longer viable. |
| **Daz3D (Genesis 9, Toon Generations 9)** | **Flagged.** The Daz standard licence permits renders, but Blender transfer relies on the community Diffeomorphic add-on. ARKit-52 is not native (third-party morph packs). Rights in third-party content vary per product. High friction for a code-driven pipeline. |
| **VRoid** | Anime style, which does not fit. It has its own VRM expression set, not full ARKit unless added. |
| **Mixamo** characters | Free and rigged, but no facial shapes. Useful only for the body-animation library (retarget onto the hero). |
| **CGTrader "Cute stylized cartoon boy, 54 ARKit blendshapes"** ($149) | Child proportions, not a 20s man. https://www.cgtrader.com/3d-models/character/child/cute-stylized-cartoon-boy-3d-character-rigged-54-blendshapes |
| **ThreeDee Hipster Man** ($69, ARP, 52 ARKit, Blender 3.6–5.2) | Viable alternative to #2 if a hipster look is acceptable. https://superhivemarket.com/products/hipster-man-cartoon-character |
| **ThreeDee Customizable Man Cartoon Low-poly** ($48, 52 ARKit, "various hats" so a cap is likely) | Viable alternative to #1, but an older, adult look. https://www.threedee.design/products/3d-models/customizable-man-cartoon-low-poly/ |
| **ThreeDee Cartoon Boy Teen / Cartoon White Teen Boy** ($88, Rigify) | The listings do not state ARKit, so they fail that requirement as listed. |
| **DanilGOE stylized bases** | The Classic Stylized edition explicitly "does not include ARKit 52". The ARKit versions are realistic, which does not fit. |
| **PO-Art "Male avatar with facial blendshapes"** (Fab, $24.49) | Full 52 ARKit, but UE-only, with no separate eye joints and an avatar look. |
| **Free "Stylized Cartoon Male Rigged Toon Young Man"** (Superhive) | Untextured, with no blendshapes stated. |

## Pre-purchase checklist (ask the seller before buying)
1. Send the exact list of shape-key names, to diff against the ARKit 52 and the viseme set our engine uses.
2. Confirm the eyeballs are separate meshes that can be rotated by bone or object, and that eyeBlink closes fully with no gap.
3. Confirm the version the .blend is saved in (we need 4.2 or older).
4. Confirm the total poly count with clothing and hair.
5. Confirm which garments are included: hoodie, joggers, sneakers, cap.

## Sources
- ThreeDee licence: https://www.threedee.design/license/
- Reallusion content policy: https://www.reallusion.com/license/content.html
- Fab licence tiers: https://dev.epicgames.com/documentation/fab/licenses-and-pricing-in-fab
- Ready Player Me shutdown: https://techcrunch.com/2025/12/19/netflix-acquires-gaming-avatar-maker-ready-player-me/
- Listing URLs are inline above.
