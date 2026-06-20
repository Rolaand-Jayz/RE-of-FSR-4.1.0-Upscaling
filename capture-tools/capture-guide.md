# FSR 4.1.0 Runtime Capture Guide

## What You Need
- Windows PC with AMD Radeon RX 9060 XT
- Latest AMD Adrenalin drivers (25.6.1 or newer)
- A game from the supported list (Cyberpunk 2077 recommended)
- RenderDoc (download from https://renderdoc.org)

## Step 1: Enable FSR 4 in AMD Adrenalin

1. Open **AMD Software: Adrenalin Edition**
2. Go to **Settings → Display**
3. Find **AMD FSR Upscaling** toggle and turn it **ON**
4. This tells the driver to auto-upgrade any FSR 3.1 game to FSR 4

## Step 2: Install RenderDoc

1. Download from https://renderdoc.org/builds
2. Run the installer (default settings are fine)
3. Open RenderDoc after install

## Step 3: Launch the Game Through RenderDoc

### For Cyberpunk 2077:
1. In RenderDoc, click **File → Launch Application**
2. Browse to the game executable:
   ```
   C:\Program Files (x86)\GOG Galaxy\Games\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe
   ```
   (or the Steam equivalent:
   ```
   C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe
   ```
   )
3. In the **Working Dir** field, set it to the same folder as the exe
4. Click **Launch**
5. The game will start with RenderDoc attached (you'll see a small overlay)

### For other games:
Same process — just point RenderDoc at the game's main .exe file.

## Step 4: Enable FSR in the Game

### Cyberpunk 2077:
1. Go to **Settings → Graphics**
2. Set **AMD FSR 3** to **ON**
3. Set the **Upscaling Method** to **AMD FSR**
4. Set quality to **Quality** or **Balanced**
5. Make sure the game is rendering at a lower resolution (not "Native")

### For other games:
Look for "FSR", "FidelityFX", "Super Resolution", or "Upscaling" in the graphics settings and enable it.

## Step 5: Capture a Frame

1. Play the game for about 30 seconds (let a scene load and stabilize)
2. Stand still in a well-lit area (not a menu, not a loading screen)
3. Press **F12** (or PrintScreen) to capture
4. You'll see a brief flash/freeze — that's the capture happening
5. Press **F12** one more time in a different scene for a second capture
6. **Alt+Tab** out of the game
7. In RenderDoc, you'll see your captures listed in the **Capture Overview**

## Step 6: Save the Capture

1. In RenderDoc, right-click the capture in the list
2. Click **Save Capture As...**
3. Save it somewhere easy to find (Desktop, named `fsr4-capture-1.rdc`)
4. **Repeat** — save the second capture as `fsr4-capture-2.rdc`

## Step 7: Send Us the Files

The `.rdc` files will be **100-500 MB each**. Options:
- Upload to Google Drive / Dropbox / OneDrive and share the link
- Or: Run the analysis script below FIRST, which produces a small JSON file

## Alternative: Run the Extraction Script (Much Smaller Output)

If the .rdc files are too big to upload, run this on the Windows machine:

1. Open RenderDoc
2. Go to **Tools → Python Shell**
3. Paste the script from `extract_dispatches.py` (provided separately)
4. It will dump a JSON file (~1-5 MB) with everything we need

## What We're Looking For

When FSR 4 is active, every frame the GPU runs **27 dispatch passes**:
```
prepass → pass1..pass12 → pass0_post..pass12_post → postpass
```

Each pass has:
- A compute shader that runs the neural network
- Weight data (the AI model parameters)
- Input/output buffers (the image data being processed)
- Configuration constants (resolution, quality preset, etc.)

RenderDoc captures ALL of this. Our analysis script extracts:
- Which dispatches are the FSR passes (vs game rendering)
- The constant buffer values per pass (tells us weight offsets)
- The resource bindings per pass (tells us data flow)
- The dispatch dimensions per pass (tells us thread counts)

This closes the gap in our reverse engineering — we have the static analysis done, we just need the live runtime data to verify it.

## Troubleshooting

**Game crashes on launch through RenderDoc:**
- Try launching the game normally first, then use RenderDoc's **Inject** feature (File → Inject into Process)

**No captures appearing:**
- Make sure F12 is the capture key (check RenderDoc settings → Keys)
- Try PrintScreen instead

**Can't find FSR option in game:**
- Make sure AMD FSR Upscaling is ON in Adrenalin
- Some games call it "Super Resolution" or "Temporal Upscaler"
- Set Anti-Aliasing to FSR/DLSS if the game has that option

**RenderDoc overlay not visible:**
- This is normal on some games — the capture still works
- Just press F12 and check if captures appear in RenderDoc after alt-tabbing
