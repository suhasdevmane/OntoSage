# Ablation attribution — T-REAL + T-REAL-SUPPLEMENT

- **v1** labels: A=5, B=1, C=5, D=32, E=6, F=0
- **v2-ablation** labels: A=4, B=2, C=5, D=31, E=7, F=0
- **v2** labels: A=5, B=1, C=6, D=32, E=5, F=0

Acceptable rate on answerable items (n = 44):

- **incidental fixes (v1 -> v2 with the architecture switched off):** 13.6% -> 13.6%, difference +0.0% (95% CI -9.1% to +9.1%); discordant: lost 2, gained 2; exact McNemar p = 1.0000
- **the compound architecture (same build, flags on vs off):** 13.6% -> 15.9%, difference +2.3% (95% CI -6.8% to +11.4%); discordant: lost 2, gained 3; exact McNemar p = 1.0000
- **total (the pre-registered primary comparison):** 13.6% -> 15.9%, difference +2.3% (95% CI -9.1% to +13.6%); discordant: lost 3, gained 4; exact McNemar p = 1.0000
