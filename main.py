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

import time

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

# 통합 보기를 고를 때 화면에 보여줄 이름
STAY_ALL = "전체 (장기+단기)"

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

# 장기외국인 / 단기외국인 / 통합(전체) 선택
stay_type = st.sidebar.radio(
    "체류 유형",
    options=[STAY_ALL, "장기외국인", "단기외국인"],
    index=0,
    help="장기외국인: 90일 이상 체류자 / 단기외국인: 90일 미만 체류자 / 전체: 둘을 합친 값",
)

# 국적 선택 (전체 보기 옵션 포함)
nat_list = ["전체 국적"] + sorted(df["국적명"].unique().tolist())
nat_choice = st.sidebar.selectbox("국적", nat_list)

st.sidebar.markdown("---")
st.sidebar.subheader("⏰ 시간대")

# 시간대를 '정지 화면'으로 볼지, '애니메이션'으로 재생할지 선택해요.
view_mode = st.sidebar.radio(
    "보기 방식",
    options=["정지 화면", "시간별 변화 애니메이션"],
)

hour_list = sorted(df["체류 시작 시간"].unique().tolist())

if view_mode == "정지 화면":
    # 슬라이더로 원하는 시간 하나를 골라요 (전체 시간 합계도 가능)
    hour_choice = st.sidebar.select_slider(
        "체류 시작 시간",
        options=["전체 시간"] + [f"{h}시" for h in hour_list],
        value="전체 시간",
    )
    play_clicked = False
    speed = None
else:
    # 애니메이션 재생 속도(프레임 사이 대기 시간)
    speed = st.sidebar.slider("재생 속도 (프레임당 초)", 0.2, 2.0, 0.6, 0.1)
    st.sidebar.caption(
        f"▶ 버튼을 누르면 {hour_list[0]}시부터 {hour_list[-1]}시까지 "
        "순서대로 변화를 보여드려요."
    )
    play_clicked = st.sidebar.button("▶ 애니메이션 재생하기", use_container_width=True)
    hour_choice = None

st.sidebar.markdown("---")
st.sidebar.caption(
    "🙈 인구수가 '*'로 표시된 데이터는 3명 미만이라 개인정보 보호를 위해 "
    "감춰진 값이에요. 지도에서는 아주 옅은 회색 점으로 따로 표시하고, "
    "합계에는 포함하지 않아요."
)
st.sidebar.caption(
    "🖱️ 지도 조작법 — 왼쪽 드래그: 이동 · 마우스 휠: 확대/축소 · "
    "오른쪽(또는 Ctrl) 드래그: 3D 회전·기울이기"
)

# ------------------------------------------------------------
# 3. 공통 함수 - 필터링 / 집계 / 색상 계산
# ------------------------------------------------------------
def 유형_국적_필터(원본, stay_type, nat_choice):
    """체류 유형과 국적만 걸러내요 (시간은 아직 그대로 둬요)."""
    결과 = 원본
    if stay_type != STAY_ALL:
        결과 = 결과[결과["장단기 외국인 구분"] == stay_type]
    if nat_choice != "전체 국적":
        결과 = 결과[결과["국적명"] == nat_choice]
    return 결과


def 격자별_집계(부분데이터):
    """위치(격자)별로 인구수를 더하고, 마스킹 여부도 함께 계산해요."""
    grouped = (
        부분데이터.groupby(["lat", "lon"])
        .agg(
            인구수=("인구수_숫자", "sum"),   # '*'(마스킹)는 NaN이라 합계에서 자동 제외돼요
            마스킹있음=("마스킹여부", "any"),
        )
        .reset_index()
    )
    grouped["인구수"] = grouped["인구수"].fillna(0)
    grouped["숫자있음"] = grouped["인구수"] > 0
    return grouped


def 색깔_계산(row, max_value):
    """인구수에 따라 노랑->주황->빨강으로 색을 칠해요. 감춰진 값은 옅은 회색으로요."""
    if not row["숫자있음"]:
        if row["마스킹있음"]:
            return [150, 150, 150, 60]  # 감춰진 값만 있는 격자: 아주 옅은 회색
        return [0, 0, 0, 0]  # 데이터 자체가 없으면 투명 처리

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


def 색과_높이_추가(grouped, max_value):
    """집계된 표에 지도용 색깔/높이 컬럼을 더해줘요."""
    grouped = grouped.copy()
    grouped["색깔"] = grouped.apply(색깔_계산, axis=1, max_value=max_value)
    # 3D 막대 높이도 인구수에 비례하게 만들어요 (완만하게 sqrt 사용)
    grouped["높이"] = np.sqrt(grouped["인구수"].clip(lower=0)) * 40
    return grouped


def 지도_만들기(grouped, 현재시간_라벨):
    """pydeck GridCellLayer로 250m 격자를 정확한 크기로 그려요."""
    layer = pdk.Layer(
        "GridCellLayer",
        data=grouped,
        get_position=["lon", "lat"],
        cell_size=CELL_SIZE_M,
        extruded=True,          # 3D로 살짝 튀어나오게
        get_elevation="높이",
        elevation_scale=1,
        get_fill_color="색깔",
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=37.5665,
        longitude=126.9780,
        zoom=10.3,
        pitch=45,   # 살짝 기울여서 3D 느낌을 살려요
        bearing=0,
    )

    tooltip = {
        "html": f"<b>{현재시간_라벨}</b><br/><b>인구수:</b> {{인구수}}명",
        "style": {"backgroundColor": "#7c2d12", "color": "white"},
    }

    # pydeck은 기본적으로 controller가 켜져 있어서(=True) 별도 설정 없이도
    # 왼쪽 드래그(이동), 마우스 휠(확대·축소), 오른쪽/Ctrl+드래그(회전·기울이기)가
    # 모두 가능해요. (pdk.Deck()에는 controller라는 매개변수가 따로 없어서
    # 여기서 넣으면 오히려 TypeError가 나니 넣지 않아요!)
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip=tooltip,
        map_style="mapbox://styles/mapbox/dark-v10",
    )
    return deck


# ------------------------------------------------------------
# 4. 화면 위쪽 - 제목
# ------------------------------------------------------------
st.title("🏙️ 서울시 체류외국인 지도")
st.write(
    "서울 곳곳, 250m 격자마다 외국인이 얼마나 머물고 있는지 "
    "따뜻한 색으로 보여드려요. 왼쪽에서 조건을 바꿔보세요!"
)

metric_col1, metric_col2, metric_col3 = st.columns(3)
map_placeholder = st.empty()
caption_placeholder = st.empty()

# ------------------------------------------------------------
# 5. 화면 그리기 - '정지 화면' 모드
# ------------------------------------------------------------
if view_mode == "정지 화면":
    filtered = 유형_국적_필터(df, stay_type, nat_choice)
    if hour_choice != "전체 시간":
        선택시간 = int(hour_choice.replace("시", ""))
        filtered = filtered[filtered["체류 시작 시간"] == 선택시간]

    grouped = 격자별_집계(filtered)

    max_value = grouped.loc[grouped["숫자있음"], "인구수"].max()
    if pd.isna(max_value) or max_value == 0:
        max_value = 1  # 나눗셈 오류 방지용 (표시할 데이터가 없을 때)

    grouped = 색과_높이_추가(grouped, max_value)

    metric_col1.metric("선택 조건 총 인구수(명)", f"{grouped['인구수'].sum():,.1f}")
    metric_col2.metric("데이터가 있는 격자 수", f"{int(grouped['숫자있음'].sum()):,}")
    metric_col3.metric(
        "감춰진(마스킹) 격자 수",
        f"{int(((~grouped['숫자있음']) & grouped['마스킹있음']).sum()):,}",
        help="3명 미만이라 값이 공개되지 않은 격자예요. 합계에는 포함되지 않았어요.",
    )

    deck = 지도_만들기(grouped, hour_choice)
    map_placeholder.pydeck_chart(deck, use_container_width=True)
    caption_placeholder.caption(
        f"현재 보기: {stay_type} · {nat_choice} · {hour_choice} · "
        "막대가 높고 붉을수록 인구가 많은 격자예요."
    )

# ------------------------------------------------------------
# 6. 화면 그리기 - '시간별 변화 애니메이션' 모드
# ------------------------------------------------------------
else:
    # 시간은 아직 거르지 않은 기준 데이터 (유형 + 국적만 반영)
    base = 유형_국적_필터(df, stay_type, nat_choice)

    # 모든 시간대에서 같은 색/높이 기준을 쓰기 위해, 전체 시간대를 통틀어
    # 가장 큰 값을 미리 한 번만 계산해둬요. (그래야 프레임마다 색이 안 바뀌어요)
    전체_격자별 = base.groupby(["lat", "lon", "체류 시작 시간"])["인구수_숫자"].sum().reset_index()
    global_max = 전체_격자별["인구수_숫자"].max()
    if pd.isna(global_max) or global_max == 0:
        global_max = 1

    if not play_clicked:
        # 아직 재생 전이면, 첫 시간대를 미리보기로 보여줘요.
        preview = base[base["체류 시작 시간"] == hour_list[0]]
        grouped = 색과_높이_추가(격자별_집계(preview), global_max)

        metric_col1.metric("선택 조건 총 인구수(명, 미리보기)", f"{grouped['인구수'].sum():,.1f}")
        metric_col2.metric("데이터가 있는 격자 수", f"{int(grouped['숫자있음'].sum()):,}")
        metric_col3.metric("전체 시간대 중 최댓값(격자당, 명)", f"{global_max:,.1f}")

        deck = 지도_만들기(grouped, f"{hour_list[0]}시 (미리보기)")
        map_placeholder.pydeck_chart(deck, use_container_width=True)
        caption_placeholder.caption(
            "왼쪽의 '▶ 애니메이션 재생하기' 버튼을 누르면 시간대별 변화가 시작돼요."
        )
    else:
        # ▶ 버튼을 눌렀을 때: 시간 순서대로 한 프레임씩 지도를 새로 그려요.
        # (재생 중에 다른 조건을 바꾸면 스트림릿이 자동으로 이 반복을 멈추고
        #  새 조건으로 다시 시작해요.)
        for h in hour_list:
            frame = base[base["체류 시작 시간"] == h]
            grouped = 색과_높이_추가(격자별_집계(frame), global_max)

            metric_col1.metric(f"{h}시 총 인구수(명)", f"{grouped['인구수'].sum():,.1f}")
            metric_col2.metric("데이터가 있는 격자 수", f"{int(grouped['숫자있음'].sum()):,}")
            metric_col3.metric("전체 시간대 중 최댓값(격자당, 명)", f"{global_max:,.1f}")

            deck = 지도_만들기(grouped, f"{h}시")
            map_placeholder.pydeck_chart(deck, use_container_width=True)
            caption_placeholder.caption(
                f"⏱️ 재생 중: {stay_type} · {nat_choice} · 지금은 **{h}시** 화면이에요."
            )

            time.sleep(speed)

        caption_placeholder.caption(
            f"✅ 재생이 끝났어요 ({hour_list[0]}시 ~ {hour_list[-1]}시). "
            "다시 보려면 재생 버튼을 한 번 더 눌러주세요."
        )
