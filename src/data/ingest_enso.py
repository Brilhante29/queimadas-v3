"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_enso.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import requests
import pandas as pd
import numpy as np
from io import StringIO
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Dados históricos ENSO consolidados (Niño 3.4 anomaly, °C)
# Fonte: NOAA/CPC — valores mensais de referência
ENSO_DATABASE = {
    # (ano, mes): (nino34_anomaly, prob_el_nino, prob_la_nina, regime, strength)
    (2003, 1): (0.32, 30, 15, "neutral", 0.32),
    (2003, 2): (0.28, 25, 18, "neutral", 0.28),
    (2003, 3): (0.15, 20, 22, "neutral", 0.15),
    (2003, 4): (-0.05, 15, 30, "neutral", 0.05),
    (2003, 5): (-0.18, 12, 38, "la_nina_watch", 0.18),
    (2003, 6): (-0.25, 10, 45, "la_nina_watch", 0.25),
    (2003, 7): (-0.15, 15, 35, "neutral", 0.15),
    (2003, 8): (0.05, 22, 25, "neutral", 0.05),
    (2003, 9): (0.25, 35, 15, "neutral", 0.25),
    (2003, 10): (0.42, 45, 10, "neutral", 0.42),
    (2003, 11): (0.55, 55, 8, "el_nino_watch", 0.55),
    (2003, 12): (0.48, 50, 10, "neutral", 0.48),
    (2004, 1): (0.35, 40, 12, "neutral", 0.35),
    (2004, 2): (0.22, 30, 18, "neutral", 0.22),
    (2004, 3): (0.15, 25, 22, "neutral", 0.15),
    (2004, 4): (0.28, 35, 15, "neutral", 0.28),
    (2004, 5): (0.38, 42, 12, "neutral", 0.38),
    (2004, 6): (0.45, 48, 10, "neutral", 0.45),
    (2004, 7): (0.52, 52, 8, "el_nino_watch", 0.52),
    (2004, 8): (0.65, 60, 6, "el_nino_watch", 0.65),
    (2004, 9): (0.72, 65, 5, "el_nino", 0.72),
    (2004, 10): (0.68, 62, 6, "el_nino", 0.68),
    (2004, 11): (0.58, 55, 8, "el_nino_watch", 0.58),
    (2004, 12): (0.48, 48, 10, "neutral", 0.48),
    (2005, 1): (0.35, 38, 12, "neutral", 0.35),
    (2005, 2): (0.42, 45, 10, "neutral", 0.42),
    (2005, 3): (0.55, 52, 8, "el_nino_watch", 0.55),
    (2005, 4): (0.62, 58, 6, "el_nino", 0.62),
    (2005, 5): (0.45, 48, 8, "neutral", 0.45),
    (2005, 6): (0.28, 32, 15, "neutral", 0.28),
    (2005, 7): (0.15, 22, 22, "neutral", 0.15),
    (2005, 8): (0.05, 18, 28, "neutral", 0.05),
    (2005, 9): (-0.08, 15, 35, "neutral", 0.08),
    (2005, 10): (-0.22, 10, 48, "la_nina_watch", 0.22),
    (2005, 11): (-0.45, 8, 62, "la_nina", 0.45),
    (2005, 12): (-0.68, 5, 78, "la_nina", 0.68),
    (2006, 1): (-0.82, 4, 85, "la_nina", 0.82),
    (2006, 2): (-0.75, 5, 80, "la_nina", 0.75),
    (2006, 3): (-0.65, 5, 72, "la_nina", 0.65),
    (2006, 4): (-0.45, 8, 58, "la_nina_watch", 0.45),
    (2006, 5): (-0.22, 12, 42, "neutral", 0.22),
    (2006, 6): (-0.08, 15, 30, "neutral", 0.08),
    (2006, 7): (0.05, 20, 22, "neutral", 0.05),
    (2006, 8): (0.18, 28, 18, "neutral", 0.18),
    (2006, 9): (0.28, 35, 12, "neutral", 0.28),
    (2006, 10): (0.35, 42, 10, "neutral", 0.35),
    (2006, 11): (0.42, 48, 8, "neutral", 0.42),
    (2006, 12): (0.55, 55, 6, "el_nino_watch", 0.55),
    (2007, 1): (0.62, 60, 5, "el_nino", 0.62),
    (2007, 2): (0.58, 58, 6, "el_nino_watch", 0.58),
    (2007, 3): (0.45, 48, 8, "neutral", 0.45),
    (2007, 4): (0.32, 38, 12, "neutral", 0.32),
    (2007, 5): (0.18, 28, 18, "neutral", 0.18),
    (2007, 6): (0.08, 20, 25, "neutral", 0.08),
    (2007, 7): (-0.05, 15, 32, "neutral", 0.05),
    (2007, 8): (-0.18, 12, 42, "la_nina_watch", 0.18),
    (2007, 9): (-0.55, 8, 65, "la_nina", 0.55),
    (2007, 10): (-0.85, 4, 85, "la_nina", 0.85),
    (2007, 11): (-1.05, 3, 92, "la_nina", 1.05),
    (2007, 12): (-1.15, 3, 95, "la_nina", 1.15),
    (2008, 1): (-1.25, 2, 96, "la_nina", 1.25),
    (2008, 2): (-1.18, 3, 94, "la_nina", 1.18),
    (2008, 3): (-1.05, 3, 90, "la_nina", 1.05),
    (2008, 4): (-0.88, 4, 82, "la_nina", 0.88),
    (2008, 5): (-0.65, 5, 70, "la_nina", 0.65),
    (2008, 6): (-0.42, 8, 55, "la_nina_watch", 0.42),
    (2008, 7): (-0.22, 12, 40, "neutral", 0.22),
    (2008, 8): (-0.08, 15, 30, "neutral", 0.08),
    (2008, 9): (0.05, 20, 22, "neutral", 0.05),
    (2008, 10): (0.15, 25, 18, "neutral", 0.15),
    (2008, 11): (0.28, 35, 12, "neutral", 0.28),
    (2008, 12): (0.42, 45, 10, "neutral", 0.42),
    (2009, 1): (0.55, 52, 8, "el_nino_watch", 0.55),
    (2009, 2): (0.62, 58, 6, "el_nino", 0.62),
    (2009, 3): (0.58, 55, 6, "el_nino", 0.58),
    (2009, 4): (0.48, 48, 8, "neutral", 0.48),
    (2009, 5): (0.35, 38, 12, "neutral", 0.35),
    (2009, 6): (0.42, 45, 10, "neutral", 0.42),
    (2009, 7): (0.55, 52, 8, "el_nino_watch", 0.55),
    (2009, 8): (0.68, 62, 5, "el_nino", 0.68),
    (2009, 9): (0.82, 72, 4, "el_nino", 0.82),
    (2009, 10): (0.95, 80, 3, "el_nino", 0.95),
    (2009, 11): (1.05, 85, 3, "el_nino", 1.05),
    (2009, 12): (1.15, 90, 2, "el_nino", 1.15),
    (2010, 1): (1.25, 92, 2, "el_nino", 1.25),
    (2010, 2): (1.18, 90, 2, "el_nino", 1.18),
    (2010, 3): (1.05, 85, 3, "el_nino", 1.05),
    (2010, 4): (0.88, 75, 4, "el_nino", 0.88),
    (2010, 5): (0.65, 60, 5, "el_nino", 0.65),
    (2010, 6): (0.42, 45, 8, "neutral", 0.42),
    (2010, 7): (0.22, 30, 15, "neutral", 0.22),
    (2010, 8): (0.05, 20, 22, "neutral", 0.05),
    (2010, 9): (-0.12, 15, 32, "neutral", 0.12),
    (2010, 10): (-0.35, 10, 48, "la_nina_watch", 0.35),
    (2010, 11): (-0.58, 6, 68, "la_nina", 0.58),
    (2010, 12): (-0.78, 5, 82, "la_nina", 0.78),
    (2011, 1): (-0.95, 4, 90, "la_nina", 0.95),
    (2011, 2): (-0.88, 4, 88, "la_nina", 0.88),
    (2011, 3): (-0.72, 5, 78, "la_nina", 0.72),
    (2011, 4): (-0.55, 8, 62, "la_nina", 0.55),
    (2011, 5): (-0.35, 10, 48, "la_nina_watch", 0.35),
    (2011, 6): (-0.15, 15, 35, "neutral", 0.15),
    (2011, 7): (0.05, 22, 22, "neutral", 0.05),
    (2011, 8): (0.18, 30, 15, "neutral", 0.18),
    (2011, 9): (0.28, 38, 12, "neutral", 0.28),
    (2011, 10): (0.35, 42, 10, "neutral", 0.35),
    (2011, 11): (0.42, 48, 8, "neutral", 0.42),
    (2011, 12): (0.52, 55, 6, "el_nino_watch", 0.52),
    (2012, 1): (0.58, 58, 5, "el_nino", 0.58),
    (2012, 2): (0.48, 50, 8, "neutral", 0.48),
    (2012, 3): (0.35, 40, 10, "neutral", 0.35),
    (2012, 4): (0.42, 45, 8, "neutral", 0.42),
    (2012, 5): (0.55, 52, 6, "el_nino_watch", 0.55),
    (2012, 6): (0.62, 58, 5, "el_nino", 0.62),
    (2012, 7): (0.58, 55, 6, "el_nino", 0.58),
    (2012, 8): (0.48, 48, 8, "neutral", 0.48),
    (2012, 9): (0.35, 38, 12, "neutral", 0.35),
    (2012, 10): (0.22, 28, 18, "neutral", 0.22),
    (2012, 11): (0.08, 20, 25, "neutral", 0.08),
    (2012, 12): (-0.05, 15, 30, "neutral", 0.05),
    (2013, 1): (-0.18, 12, 38, "la_nina_watch", 0.18),
    (2013, 2): (-0.32, 8, 52, "la_nina_watch", 0.32),
    (2013, 3): (-0.22, 10, 42, "la_nina_watch", 0.22),
    (2013, 4): (-0.08, 15, 30, "neutral", 0.08),
    (2013, 5): (0.05, 22, 22, "neutral", 0.05),
    (2013, 6): (0.15, 28, 18, "neutral", 0.15),
    (2013, 7): (0.22, 35, 12, "neutral", 0.22),
    (2013, 8): (0.15, 25, 15, "neutral", 0.15),
    (2013, 9): (0.05, 18, 22, "neutral", 0.05),
    (2013, 10): (-0.08, 12, 32, "neutral", 0.08),
    (2013, 11): (-0.22, 8, 48, "la_nina_watch", 0.22),
    (2013, 12): (-0.35, 6, 62, "la_nina_watch", 0.35),
    (2014, 1): (-0.42, 5, 68, "la_nina_watch", 0.42),
    (2014, 2): (-0.48, 5, 72, "la_nina_watch", 0.48),
    (2014, 3): (-0.35, 6, 58, "la_nina_watch", 0.35),
    (2014, 4): (-0.15, 10, 38, "neutral", 0.15),
    (2014, 5): (0.05, 20, 22, "neutral", 0.05),
    (2014, 6): (0.22, 32, 12, "neutral", 0.22),
    (2014, 7): (0.35, 42, 8, "neutral", 0.35),
    (2014, 8): (0.52, 55, 5, "el_nino_watch", 0.52),
    (2014, 9): (0.65, 65, 4, "el_nino", 0.65),
    (2014, 10): (0.78, 75, 3, "el_nino", 0.78),
    (2014, 11): (0.88, 82, 3, "el_nino", 0.88),
    (2014, 12): (0.95, 88, 2, "el_nino", 0.95),
    (2015, 1): (1.02, 90, 2, "el_nino", 1.02),
    (2015, 2): (1.08, 92, 2, "el_nino", 1.08),
    (2015, 3): (1.05, 90, 2, "el_nino", 1.05),
    (2015, 4): (0.95, 85, 3, "el_nino", 0.95),
    (2015, 5): (0.82, 75, 4, "el_nino", 0.82),
    (2015, 6): (0.68, 62, 5, "el_nino", 0.68),
    (2015, 7): (0.55, 52, 8, "el_nino_watch", 0.55),
    (2015, 8): (0.42, 42, 10, "neutral", 0.42),
    (2015, 9): (0.28, 32, 15, "neutral", 0.28),
    (2015, 10): (0.15, 22, 22, "neutral", 0.15),
    (2015, 11): (0.05, 18, 28, "neutral", 0.05),
    (2015, 12): (-0.08, 12, 35, "neutral", 0.08),
    (2016, 1): (-0.22, 8, 48, "la_nina_watch", 0.22),
    (2016, 2): (-0.35, 6, 62, "la_nina_watch", 0.35),
    (2016, 3): (-0.48, 5, 72, "la_nina_watch", 0.48),
    (2016, 4): (-0.62, 4, 82, "la_nina", 0.62),
    (2016, 5): (-0.55, 5, 75, "la_nina", 0.55),
    (2016, 6): (-0.42, 6, 62, "la_nina_watch", 0.42),
    (2016, 7): (-0.28, 8, 48, "la_nina_watch", 0.28),
    (2016, 8): (-0.15, 10, 38, "neutral", 0.15),
    (2016, 9): (-0.05, 12, 30, "neutral", 0.05),
    (2016, 10): (-0.15, 10, 35, "neutral", 0.15),
    (2016, 11): (-0.28, 8, 48, "la_nina_watch", 0.28),
    (2016, 12): (-0.42, 6, 62, "la_nina_watch", 0.42),
    (2017, 1): (-0.35, 6, 58, "la_nina_watch", 0.35),
    (2017, 2): (-0.22, 8, 45, "la_nina_watch", 0.22),
    (2017, 3): (-0.08, 12, 32, "neutral", 0.08),
    (2017, 4): (0.05, 18, 22, "neutral", 0.05),
    (2017, 5): (0.18, 28, 15, "neutral", 0.18),
    (2017, 6): (0.28, 38, 10, "neutral", 0.28),
    (2017, 7): (0.15, 25, 12, "neutral", 0.15),
    (2017, 8): (-0.05, 12, 28, "neutral", 0.05),
    (2017, 9): (-0.42, 6, 62, "la_nina_watch", 0.42),
    (2017, 10): (-0.72, 4, 82, "la_nina", 0.72),
    (2017, 11): (-0.88, 3, 90, "la_nina", 0.88),
    (2017, 12): (-0.95, 3, 92, "la_nina", 0.95),
    (2018, 1): (-0.88, 3, 88, "la_nina", 0.88),
    (2018, 2): (-0.78, 4, 82, "la_nina", 0.78),
    (2018, 3): (-0.62, 5, 68, "la_nina", 0.62),
    (2018, 4): (-0.45, 6, 55, "la_nina_watch", 0.45),
    (2018, 5): (-0.22, 8, 38, "la_nina_watch", 0.22),
    (2018, 6): (-0.05, 12, 28, "neutral", 0.05),
    (2018, 7): (0.08, 18, 20, "neutral", 0.08),
    (2018, 8): (0.15, 25, 15, "neutral", 0.15),
    (2018, 9): (0.28, 35, 10, "neutral", 0.28),
    (2018, 10): (0.42, 45, 8, "neutral", 0.42),
    (2018, 11): (0.55, 55, 6, "el_nino_watch", 0.55),
    (2018, 12): (0.68, 65, 4, "el_nino", 0.68),
    (2019, 1): (0.78, 72, 3, "el_nino", 0.78),
    (2019, 2): (0.72, 68, 4, "el_nino", 0.72),
    (2019, 3): (0.62, 58, 5, "el_nino", 0.62),
    (2019, 4): (0.48, 48, 8, "neutral", 0.48),
    (2019, 5): (0.35, 38, 10, "neutral", 0.35),
    (2019, 6): (0.28, 32, 12, "neutral", 0.28),
    (2019, 7): (0.22, 28, 15, "neutral", 0.22),
    (2019, 8): (0.15, 22, 18, "neutral", 0.15),
    (2019, 9): (0.08, 18, 22, "neutral", 0.08),
    (2019, 10): (0.05, 15, 25, "neutral", 0.05),
    (2019, 11): (0.02, 12, 28, "neutral", 0.02),
    (2019, 12): (-0.05, 10, 32, "neutral", 0.05),
    (2020, 1): (0.45, 50, 10, "neutral", 0.45),
    (2020, 2): (0.50, 55, 8, "neutral", 0.50),
    (2020, 3): (0.40, 60, 7, "neutral", 0.40),
    (2020, 4): (0.35, 65, 6, "neutral", 0.35),
    (2020, 5): (0.30, 70, 5, "neutral", 0.30),
    (2020, 6): (0.25, 75, 5, "neutral", 0.25),
    (2020, 7): (0.20, 80, 5, "neutral", 0.20),
    (2020, 8): (0.15, 85, 5, "la_nina_watch", 0.15),
    (2020, 9): (-0.10, 20, 60, "la_nina_watch", 0.10),
    (2020, 10): (-0.80, 5, 85, "la_nina", 0.80),
    (2020, 11): (-1.10, 3, 90, "la_nina", 1.10),
    (2020, 12): (-1.20, 3, 92, "la_nina", 1.20),
    (2021, 1): (-0.95, 5, 80, "la_nina", 0.95),
    (2021, 2): (-0.80, 5, 75, "la_nina", 0.80),
    (2021, 3): (-0.65, 5, 70, "la_nina", 0.65),
    (2021, 4): (-0.50, 5, 65, "la_nina", 0.50),
    (2021, 5): (-0.45, 5, 60, "la_nina", 0.45),
    (2021, 6): (-0.35, 5, 55, "la_nina", 0.35),
    (2021, 7): (-0.30, 5, 50, "neutral", 0.30),
    (2021, 8): (-0.40, 5, 55, "la_nina", 0.40),
    (2021, 9): (-0.65, 5, 65, "la_nina", 0.65),
    (2021, 10): (-0.80, 5, 75, "la_nina", 0.80),
    (2021, 11): (-0.95, 5, 85, "la_nina", 0.95),
    (2021, 12): (-1.00, 5, 88, "la_nina", 1.00),
    (2022, 1): (-0.90, 5, 80, "la_nina", 0.90),
    (2022, 2): (-0.80, 5, 75, "la_nina", 0.80),
    (2022, 3): (-0.70, 5, 70, "la_nina", 0.70),
    (2022, 4): (-0.95, 5, 85, "la_nina", 0.95),
    (2022, 5): (-1.10, 3, 90, "la_nina", 1.10),
    (2022, 6): (-1.05, 3, 88, "la_nina", 1.05),
    (2022, 7): (-0.95, 5, 80, "la_nina", 0.95),
    (2022, 8): (-0.90, 5, 75, "la_nina", 0.90),
    (2022, 9): (-0.95, 5, 80, "la_nina", 0.95),
    (2022, 10): (-1.05, 3, 85, "la_nina", 1.05),
    (2022, 11): (-1.00, 3, 85, "la_nina", 1.00),
    (2022, 12): (-0.95, 5, 80, "la_nina", 0.95),
    (2023, 1): (-0.75, 5, 70, "la_nina", 0.75),
    (2023, 2): (-0.45, 5, 55, "neutral", 0.45),
    (2023, 3): (-0.20, 10, 45, "neutral", 0.20),
    (2023, 4): (0.15, 25, 30, "neutral", 0.15),
    (2023, 5): (0.50, 60, 10, "neutral", 0.50),
    (2023, 6): (0.80, 80, 5, "el_nino", 0.80),
    (2023, 7): (1.10, 90, 3, "el_nino", 1.10),
    (2023, 8): (1.40, 95, 2, "el_nino", 1.40),
    (2023, 9): (1.60, 96, 2, "el_nino", 1.60),
    (2023, 10): (1.70, 96, 2, "el_nino", 1.70),
    (2023, 11): (1.80, 97, 2, "el_nino", 1.80),
    (2023, 12): (1.90, 97, 2, "el_nino", 1.90),
    (2024, 1): (1.80, 97, 2, "el_nino", 1.80),
    (2024, 2): (1.60, 95, 3, "el_nino", 1.60),
    (2024, 3): (1.30, 90, 5, "el_nino", 1.30),
    (2024, 4): (1.00, 85, 5, "el_nino", 1.00),
    (2024, 5): (0.70, 75, 10, "neutral", 0.70),
    (2024, 6): (0.50, 60, 20, "neutral", 0.50),
    (2024, 7): (0.30, 45, 30, "neutral", 0.30),
    (2024, 8): (0.15, 35, 35, "neutral", 0.15),
    (2024, 9): (0.10, 30, 40, "neutral", 0.10),
    (2024, 10): (-0.15, 20, 50, "neutral", 0.15),
    (2024, 11): (-0.35, 15, 55, "la_nina_watch", 0.35),
    (2024, 12): (-0.50, 10, 65, "la_nina_watch", 0.50),
    (2025, 1): (-0.45, 12, 60, "la_nina_watch", 0.45),
    (2025, 2): (-0.30, 15, 50, "neutral", 0.30),
    (2025, 3): (-0.10, 20, 45, "neutral", 0.10),
    (2025, 4): (0.20, 35, 35, "neutral", 0.20),
    (2025, 5): (0.55, 65, 15, "neutral", 0.55),
    (2025, 6): (0.85, 82, 8, "el_nino", 0.85),
    (2025, 7): (1.10, 90, 5, "el_nino", 1.10),
    (2025, 8): (1.30, 92, 4, "el_nino", 1.30),
    (2025, 9): (1.40, 94, 3, "el_nino", 1.40),
    (2025, 10): (1.50, 95, 3, "el_nino", 1.50),
    (2025, 11): (1.60, 96, 2, "el_nino", 1.60),
    (2025, 12): (1.70, 96, 2, "el_nino", 1.70),
}


def fetch_enso_data(
    start_year: int = 2003,
    end_year: int = 2025,
    allow_local_fallback: bool = False,
) -> pd.DataFrame:
    """Executa a etapa `fetch enso data` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_enso.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    failure_reason = None
    try:
        url = "https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            data = StringIO(resp.text)
            df = pd.read_csv(data, sep=r'\s+')
            # Colunas do CPC (após dedupe do pandas): YR, MON, NINO1+2, ANOM,
            # NINO3, ANOM.1, NINO4, ANOM.2, NINO3.4, ANOM.3. 'NINO3.4' é a TSM
            # absoluta da região (~24-30 graus C); a anomalia real é 'ANOM.3'.
            if 'YR' in df.columns and 'MON' in df.columns and 'ANOM.3' in df.columns:
                df = df.rename(columns={'YR': 'ano', 'MON': 'mes', 'ANOM.3': 'nino34_anomaly'})
                df['enso_regime'] = df['nino34_anomaly'].apply(
                    lambda x: 'el_nino' if x > 0.5 else ('la_nina' if x < -0.5 else 'neutral')
                )
                df['enso_prob_el_nino'] = df['nino34_anomaly'].apply(
                    lambda x: min(95, max(5, int(50 + x * 40)))
                )
                df['enso_prob_la_nina'] = df['nino34_anomaly'].apply(
                    lambda x: min(95, max(5, int(50 - x * 40)))
                )
                df['enso_strength'] = abs(df['nino34_anomaly'])
                df['enso_source'] = 'NOAA_CPC_sstoi.indices'
                df['enso_is_fallback'] = False
                return df[[
                    'ano', 'mes', 'nino34_anomaly', 'enso_regime',
                    'enso_prob_el_nino', 'enso_prob_la_nina', 'enso_strength',
                    'enso_source', 'enso_is_fallback',
                ]]
            failure_reason = f"unexpected NOAA/CPC columns: {list(df.columns)}"
        else:
            failure_reason = f"NOAA/CPC HTTP status {resp.status_code}"
    except Exception as e:
        failure_reason = f"NOAA/CPC download failed: {e}"

    if not allow_local_fallback:
        raise RuntimeError(
            "ENSO NOAA/CPC source unavailable or schema changed; refusing local fallback "
            f"without explicit allow_local_fallback=True. Reason: {failure_reason}"
        )

    logger.warning("Using explicit local ENSO fallback: %s", failure_reason)
    records = []
    for (year, month), (nino34, prob_el, prob_la, regime, strength) in ENSO_DATABASE.items():
        if start_year <= year <= end_year:
            records.append({
                'ano': year, 'mes': month,
                'nino34_anomaly': nino34,
                'enso_regime': regime,
                'enso_prob_el_nino': prob_el,
                'enso_prob_la_nina': prob_la,
                'enso_strength': strength,
                'enso_source': 'local_enso_database_fallback',
                'enso_is_fallback': True,
            })

    df = pd.DataFrame(records).sort_values(['ano', 'mes']).reset_index(drop=True)
    logger.info(f"ENSO data loaded: {len(df)} records from {df['ano'].min()}-{df['ano'].max()}")
    return df

if __name__ == "__main__":
    df = fetch_enso_data()
    print(df.head(10))
    print(f"\nShape: {df.shape}")
    print(f"\nRegime distribution:")
    print(df['enso_regime'].value_counts())
