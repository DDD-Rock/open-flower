# Design QA: Windows / latest macOS parity

## Reference and implementation

- Reference: NetEase UU Remote Desktop, window `Huawei Mac mini`, captured from the current macOS client on 2026-08-03.
- Reference captures: `C:\Users\Rock\AppData\Local\Temp\open-flower-mac-ui-reference-latest\recapture\`.
- Final Windows captures: `C:\Users\Rock\AppData\Local\Temp\open-flower-windows-ui-latest\`.
- Reference viewport: 3862 x 2122 physical pixels; the application crop was normalized for comparison.
- Implementation viewport: 640 x 800 logical pixels (960 x 1200 at device pixel ratio 1.5).
- States checked: dead flower, live flower, temple, follow/heal, and monitor; default configuration page plus log/tools navigation availability.

## Comparison history

1. The first reference was an older remote-viewer window. It was discarded after the user identified NetEase UU Remote Desktop as the latest macOS client.
2. The first Windows pass retained too much of the legacy stacked-card layout. It was replaced with the macOS two-column shell: persistent left mode navigation, right title/tabs/content, and fixed footer action.
3. The mode-specific row order, temple/display selectors, icon coloring, and aspect ratio still differed. Rows were reordered to match macOS, selectors were converted to segmented controls, icons were normalized to the macOS blue/gray treatment, and the window was changed to 640 x 800.

## Final rubric

| Category | Result | Notes |
| --- | --- | --- |
| Layout | Pass | Two-column hierarchy, header tabs, content card, and fixed footer align with the reference. |
| Typography | Pass | Heading/body hierarchy and compact density are consistent with the reference. |
| Color | Pass | White surfaces, pale-blue canvas, gray borders, and blue selected/action states match. |
| Spacing | Pass | Navigation rhythm, card padding, row spacing, and footer separation are consistent across all five modes. |
| Responsiveness | Pass | Fixed desktop utility window renders without overlap or clipping at the intended 640 x 800 logical size. |
| States | Pass | Selected mode, segmented selectors, monitor-only tab behavior, disabled/running controls, and footer CTA states remain represented. |

## Residual platform differences

- Windows native spin-box arrows and a few system icon silhouettes differ slightly from macOS controls.
- Windows-only account/game-window status rows remain in the sidebar because they expose existing client capabilities.
- Live map and EXP values differ from the reference by design; their placement and visual treatment match.

No remaining P0, P1, or P2 visual discrepancies were found. Residual differences are P3 platform details and do not affect hierarchy, behavior, or usability.

Final result: **passed**.
