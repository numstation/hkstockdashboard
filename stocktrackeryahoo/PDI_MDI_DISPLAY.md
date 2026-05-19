# PDI and MDI Display in UI

## ✅ PDI and MDI Now Prominently Displayed

### What's Shown:

1. **PDI (DMI+)** - Plus Directional Indicator
   - Displayed in blue box with prominent styling
   - Label: "PDI (DMI+)"
   - This is the Plus Directional Indicator from Futu's formula

2. **MDI (DMI-)** - Minus Directional Indicator
   - Displayed in red box with prominent styling
   - Label: "MDI (DMI-)"
   - This is the Minus Directional Indicator from Futu's formula

### Location in UI:

The PDI and MDI values appear right after ADX and ADX Slope in the indicator details section, making it easy to:
- Compare with Futu's values
- See the difference between our calculation and Futu's
- Understand the directional movement components

### How to Compare:

1. Run analysis in the web app
2. Note the PDI and MDI values shown
3. Compare with Futu app's PDI and MDI values
4. If they match, ADX should also match
5. If they differ, that's where the ADX difference comes from

### Formula Reference:

From Futu:
- **PDI** = DMP * 100 / MTR
- **MDI** = DMM * 100 / MTR
- **ADX** = EXPMEMA(ABS(MDI-PDI) / (MDI+PDI) * 100, 14)

So if PDI and MDI match Futu, but ADX doesn't, the issue is in the ADX smoothing.
If PDI and MDI don't match, the issue is in the MTR, DMP, or DMM calculation.
