# -*- coding: utf-8 -*-
"""
서울시 체류외국인 지도
------------------------------------------------
서울시 250m 격자 단위 '체류시간대별 외국인 인구' 데이터를
지도 위에 3D 막대(격자)로 보여주는 스트림릿 앱이에요.

이 파일과 같은 폴더(또는 리포지토리 루트)에 아래 두 CSV 파일을
꼭 함께 올려주세요. 파일 이름이 다르면 아래 FILE_LONG / FILE_SHORT
변수만 바꿔주면 됩니다.
    - SEOUL_STYTIME_05_250M_OPEN_FORN_LONG_20260716.csv   (장기외국인)
    - SEOUL_STYTIME_06_250M_OPEN_FORN_SHORT_20260716.csv  (단기외국인)
"""

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from pyproj import Transformer

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
# CSV 파일 이름 (같은 폴더에 있어야 해요. 이름이 다르면 여기만 바꿔주세요!)
FILE_LONG = "SEOUL_STYTIME_05_250M_OPEN_FORN_LONG_20260716.csv"
FILE_SHORT = "SEOUL_STYTIME_06_250M_OPEN_FORN_SHORT_20260716.csv"

# 250m 격자의 한 변 길이(미터) - 데이터 이름에 있는 그대로예요.
CELL_SIZE_M = 250

st.set_page_config(
    page_title="서울시 체류외국인 지도",
    page_icon="🏙️",
    layout="wide",
)

# ------------------------------------------------------------
# 1. 데이터 불러오기 + 전처리 (한 번만 계산하고 캐시에 저장해요)
# ------------------------------------------------------------
@st.cache_data(show_spinner="데이터를 불러오는 중이에요... 조금만 기다려주세요 ☕")
def load_data():
    """CSV 두 개를 읽어서 하나로 합치고, 지도에 쓸 수 있게 다듬어요."""

    # 이 공공데이터는 한글이 CP949(EUC-KR)로 인코딩되어 있어요.
    # 보통의 utf-8로 읽으면 깨지기 때문에 encoding="cp949"를 꼭 넣어줍니다.
    df_long = pd.read_csv(FILE_LONG, encoding="cp949")
    df_short = pd.read_csv(FILE_SHORT, encoding="cp949")
    df = pd.concat([df_long, df_short], ignore_index=True)

    # 컬럼 이름 앞에 이상한 문자(BOM)와 따옴표가 붙어 나올 때가 있어서 깨끗하게 정리해요.
    df.columns = [c.strip().strip('"').replace("?", "").replace('"', "") for c in df.columns]

    # '인구수' 컬럼에는 숫자 대신 '*' 표시가 섞여 있어요.
    # 이건 개인정보 보호를 위해 3명 미만인 경우 값을 감춘 것이에요(마스킹).
    df["마스킹여부"] = df["인구수"] == "*"
    df["인구수_숫자"] = pd.to_numeric(df["인구수"], errors="coerce")  # '*' -> 결측치(NaN)

    # ------------------------------------------------------------
    # 좌표 변환: 250m 격자 좌표 -> 위도/경도
    # ------------------------------------------------------------
    # 이 데이터의 X, Y 좌표는 우리가 아는 위도/경도가 아니라
    # 'EPSG:5179 (Korea 2000 / Unified CS)'라는 우리나라 전용 좌표계예요.
    # 지도에 정확히 표시하려면 위도/경도(EPSG:4326)로 바꿔줘야 해요.
    transformer = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    # 격자 좌표는 보통 셀의 '왼쪽 아래 모서리' 기준이라,
    # 셀 정중앙에 점을 찍기 위해 반 칸(125m)만큼 더해줘요.
    half = CELL_SIZE_M / 2
    lon, lat = transformer.transform(
        df["250m 격자X좌표"].to_numpy() + half,
        df["250m 격자Y좌표"].to_numpy() + half,
    )
    df["lon"] = lon
    df["lat"] = lat

    return df


df = load_data()

# ------------------------------------------------------------
# 2. 사이드바 - 사용자가 조건을 고르는 곳
# ------------------------------------------------------------
st.sidebar.title("🔍 조건을 골라보세요")

# 장기외국인 / 단기외국인 선택
stay_type = st.sidebar.radio(
    "체류 유형",
    options=["장기외국인", "단기외국인"],
    help="장기외국인: 90일 이상 체류자 / 단기외국인: 90일 미만 체류자",
)

# 국적 선택 (전체 보기 옵션 포함)
nat_list = ["전체 국적"] + sorted(df["국적명"].unique().tolist())
nat_choice = st.sidebar.selectbox("국적", nat_list)

# 시간대 선택 (전체 보기 옵션 포함)
hour_list = sorted(df["체류 시작 시간"].unique().tolist())
hour_choice = st.sidebar.select_slider(
    "체류 시작 시간",
    options=["전체 시간"] + [f"{h}시" for h in hour_list],
    value="전체 시간",
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "🙈 인구수가 '*'로 표시된 데이터는 3명 미만이라 개인정보 보호를 위해 "
    "감춰진 값이에요. 지도에서는 아주 옅은 회색 점으로 따로 표시하고, "
    "합계에는 포함하지 않아요."
)

# ------------------------------------------------------------
# 3. 선택한 조건에 맞게 데이터 걸러내기
# ------------------------------------------------------------
filtered = df[df["장단기 외국인 구분"] == stay_type].copy()

if nat_choice != "전체 국적":
    filtered = filtered[filtered["국적명"] == nat_choice]

if hour_choice != "전체 시간":
    선택시간 = int(hour_choice.replace("시", ""))
    filtered = filtered[filtered["체류 시작 시간"] == 선택시간]

# ------------------------------------------------------------
# 4. 격자(위치)별로 합쳐서 지도에 그릴 준비를 해요
# ------------------------------------------------------------
grouped = (
    filtered.groupby(["lat", "lon"])
    .agg(
        인구수=("인구수_숫자", "sum"),          # 마스킹(*)된 값은 NaN이라 자동으로 제외되고 더해져요
        마스킹있음=("마스킹여부", "any"),          # 이 격자에 감춰진 값이 하나라도 있었는지
    )
    .reset_index()
)
grouped["인구수"] = grouped["인구수"].fillna(0)

# 완전히 감춰진(합계가 0이면서 마스킹만 있는) 격자와,
# 실제 숫자가 있는 격자를 구분해요.
grouped["숫자있음"] = grouped["인구수"] > 0

# ------------------------------------------------------------
# 5. 지도에 그릴 색깔 정하기 (따뜻한 노랑 -> 주황 -> 빨강)
# ------------------------------------------------------------
max_value = grouped.loc[grouped["숫자있음"], "인구수"].max()
if pd.isna(max_value) or max_value == 0:
    max_value = 1  # 나눗셈 오류 방지용 (표시할 데이터가 없을 때)


def 색깔_계산(row):
    """인구수에 따라 노랑->주황->빨강으로 색을 칠해요. 감춰진 값은 옅은 회색으로요."""
    if not row["숫자있음"]:
        if row["마스킹있음"]:
            # 감춰진 값만 있는 격자: 아주 옅은 회색 (집계에는 포함 안 함)
            return [150, 150, 150, 60]
        else:
            return [0, 0, 0, 0]  # 데이터 자체가 없으면 투명 처리

    # 값이 클수록 진한 빨강, 작을수록 밝은 노랑이 되도록 계산해요.
    # 격자별 인구 편차가 커서 제곱근(sqrt)으로 완만하게 눌러줘요.
    비율 = np.sqrt(row["인구수"] / max_value)
    비율 = min(max(비율, 0), 1)

    # 노랑(255,237,160) -> 주황(249,115,22) -> 빨강(153,27,27) 그라데이션
    if 비율 < 0.5:
        t = 비율 / 0.5
        r = 255 + (249 - 255) * t
        g = 237 + (115 - 237) * t
        b = 160 + (22 - 160) * t
    else:
        t = (비율 - 0.5) / 0.5
        r = 249 + (153 - 249) * t
        g = 115 + (27 - 115) * t
        b = 22 + (27 - 22) * t

    return [int(r), int(g), int(b), 200]


grouped["색깔"] = grouped.apply(색깔_계산, axis=1)
# 3D 막대 높이도 인구수에 비례하게 만들어요 (완만하게 sqrt 사용)
grouped["높이"] = np.sqrt(grouped["인구수"].clip(lower=0)) * 40

# ------------------------------------------------------------
# 6. 화면 위쪽 - 제목과 요약 숫자
# ------------------------------------------------------------
st.title("🏙️ 서울시 체류외국인 지도")
st.write(
    "서울 곳곳, 250m 격자마다 외국인이 얼마나 머물고 있는지 "
    "따뜻한 색으로 보여드려요. 왼쪽에서 조건을 바꿔보세요!"
)

col1, col2, col3 = st.columns(3)
col1.metric("선택 조건 총 인구수(명)", f"{grouped['인구수'].sum():,.1f}")
col2.metric("데이터가 있는 격자 수", f"{int(grouped['숫자있음'].sum()):,}")
col3.metric(
    "감춰진(마스킹) 격자 수",
    f"{int(((~grouped['숫자있음']) & grouped['마스킹있음']).sum()):,}",
    help="3명 미만이라 값이 공개되지 않은 격자예요. 합계에는 포함되지 않았어요.",
)

# ------------------------------------------------------------
# 7. 지도 그리기 (pydeck의 GridCellLayer로 250m 격자를 정확하게 표현해요)
# ------------------------------------------------------------
layer = pdk.Layer(
    "GridCellLayer",
    data=grouped,
    get_position=["lon", "lat"],
    cell_size=CELL_SIZE_M,
    extruded=True,                  # 3D로 살짝 튀어나오게
    get_elevation="높이",
    elevation_scale=1,
    get_fill_color="색깔",
    pickable=True,
    auto_highlight=True,
)

# 지도 초기 시점: 서울시청 근처를 중심으로 시작해요.
view_state = pdk.ViewState(
    latitude=37.5665,
    longitude=126.9780,
    zoom=10.3,
    pitch=45,   # 살짝 기울여서 3D 느낌을 살려요
    bearing=0,
)

tooltip = {
    "html": "<b>인구수:</b> {인구수}명<br/><b>위도:</b> {lat}<br/><b>경도:</b> {lon}",
    "style": {"backgroundColor": "#7c2d12", "color": "white"},
}

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/dark-v10",
)

st.pydeck_chart(deck, use_container_width=True)

st.caption(
    f"현재 보기: {stay_type} · {nat_choice} · {hour_choice} · "
    "막대가 높고 붉을수록 인구가 많은 격자예요."
)
