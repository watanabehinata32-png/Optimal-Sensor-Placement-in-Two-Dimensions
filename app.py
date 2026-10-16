import streamlit as st
import numpy as np
import pandas as pd
import json
import os
from amplify import VariableGenerator, AmplifyAEClient, solve, less_equal, greater_equal
from datetime import timedelta
from helpers import make_covers, coverage_reward, draw_map  # 長い計算と地図の描き方は helpers.py にある

st.set_page_config(page_title='センサー配置最適化', layout='wide')

# テキスト表示
st.title('📡センサーを最適に配置しよう📡')
st.write('センサーの性能や市町村の必要値を変えて、QUBOを実行すると、総コストと配置が地図でわかります')

# アクセストークン（手元では .streamlit/secrets.toml、Render では Environment Variables の AMPLIFY_TOKEN を読み込む）
try:
    token = st.secrets['AMPLIFY_TOKEN']
except Exception:
    token = os.environ.get('AMPLIFY_TOKEN', '')

# 計算の条件（サイドバーで設定する）
with st.sidebar:
    st.header('⚙️計算の条件')
    # マス目の中心点がセンサーの円に入っていれば「覆われている」と数える
    grid = st.number_input('マス目の大きさ（m）', value=500, step=100, min_value=100)
    st.caption(f'{grid} m × {grid} m のマス目でカバー率を数えます（QUBO と合否判定で共通）')
    st.subheader('ソルバー')
    time_limit = st.number_input('Amplify AE のタイムアウト（ミリ秒）', value=5000, step=500, min_value=100)

    # カバー率の重みは普段さわらないので、下の方に折りたたんでおく
    st.divider()
    with st.expander('詳しい設定（カバー率の重み）'):
        st.caption('カバー率が足りない市町村（❌）が出たら λ_cov を上げます。\n'
                   '全部✅でコストを下げたいときは少し下げます。')
        lam_cov = st.number_input('カバー率（λ_cov）', value=4.0, step=0.5)


# ============================================================
# データを用意
# ============================================================
data = json.load(open('data/data_transformed.json', encoding='utf-8'))  # QQG 資料とか と同じデータ
munis = data['municipalities']                # 市町村（8つ）
sensor_specs = data['sensor_specifications']  # センサーの種類（3つ）

# 中央市（M06）のカバー率下限は元データでは 100% だが、ほぼ達成できないのでアプリでは 95% から始める
munis[5]['required_coverage_rate'] = 0.95

# センサーの性能と市町村の必要値をタブで編集できるようにする
tab1, tab2 = st.tabs(['📡センサーの性能', '🏘️市町村の必要値'])

with tab1:
    sensor_table = pd.DataFrame({
        '名称': [s['name'] for s in sensor_specs],
        'コスト': [s['unit_procurement_cost'] for s in sensor_specs],
        '半径(km)': [s['effective_coverage_radius'] for s in sensor_specs],
        'α値': [s['alpha_field_response'] for s in sensor_specs],
        'β値': [s['beta_density_resolution'] for s in sensor_specs],
    })
    sensor_table = st.data_editor(sensor_table, hide_index=True, width='stretch')

with tab2:
    muni_table = pd.DataFrame({
        '市町村': [m['name'].split(' (')[0] for m in munis],
        '候補地点の数': [len(m['candidate_locations']) for m in munis],
        'α必要量': [m['required_alpha_response'] for m in munis],
        'β必要量': [m['required_beta_resolution'] for m in munis],
        'カバー率下限': [m['required_coverage_rate'] for m in munis],
    })
    muni_table = st.data_editor(muni_table, hide_index=True, width='stretch', disabled=['市町村', '候補地点の数'])
    st.caption('※ 中央市のカバー率下限は、元データの 100% から 95% に調整しています')

# 隣の市町村に置いたセンサーのはみ出しもカバー率に数えるか
cross = st.toggle('隣の市町村に置いたセンサーのはみ出しもカバー率に数える', value=False)

# 表から値を取り出す
cost = sensor_table['コスト'].to_numpy(dtype=float)              # 種類 k のコスト
radius = sensor_table['半径(km)'].to_numpy(dtype=float) * 1000  # 半径（座標が m なので m に直す）
alpha = sensor_table['α値'].to_numpy(dtype=float)
beta = sensor_table['β値'].to_numpy(dtype=float)
need_a = muni_table['α必要量'].to_numpy(dtype=float)            # 市町村 m の α 必要量
need_b = muni_table['β必要量'].to_numpy(dtype=float)
need_c = muni_table['カバー率下限'].to_numpy(dtype=float)

# 候補地点を1つのリストにまとめる（px, py: 座標、pm: どの市町村の地点か）
points = [c for m in munis for c in m['candidate_locations']]
px = np.array([c['x'] for c in points])
py = np.array([c['y'] for c in points])
pm = np.array([m for m, muni in enumerate(munis) for c in muni['candidate_locations']])
N = len(points)        # 候補地点の数（86）
K = len(sensor_specs)  # センサーの種類（3）
M = len(munis)         # 市町村の数（8）

# カバー率を数えるマス目（covers[m][g, i, k] = True なら、市町村 m のマス目 g を、地点 i の種類 k のセンサーが覆う）
covers = make_covers(munis, px, py, pm, radius, grid, cross)


# 実行ボタンを表示
button = st.button('QUBOを実行', type='primary')

if button and not token:
    st.error('Amplify のアクセストークンが設定されていません（AMPLIFY_TOKEN）')

elif button:
    # ============================================================
    # 変数を発行
    # ============================================================
    # x[i, k] = 1 なら「地点 i に種類 k のセンサーを置く」
    gen = VariableGenerator()
    x = gen.array('Binary', shape=(N, K))

    # ============================================================
    # コスト関数
    # ============================================================
    # 置いたセンサーのコストの合計（ほかの項と大きさをそろえるため 1/100 にする）
    total_cost = (cost[np.newaxis, :] / 100 * x).sum()

    # カバー率の報酬：マス目が覆われるほど得をする（くわしい考え方は helpers.py の coverage_reward）
    coverage = coverage_reward(x, covers, need_c, lam_cov)

    # ============================================================
    # 罰金項（制約）
    # ============================================================
    # 制約の重みは Amplify AE が自分で調整するので、ここでは重みを付けない
    # 1つの地点には1台まで
    penalty_one = less_equal(x, 1, axis=1)

    # 市町村ごとに α の合計 ≥ 必要量、β の合計 ≥ 必要量
    penalty_ab = 0
    for m in range(M):
        idx = np.nonzero(pm == m)[0]       # 市町村 m の地点の番号（連続して並んでいる）
        xm = x[idx[0]:idx[-1] + 1]         # 市町村 m の地点の変数
        penalty_ab += greater_equal((alpha[np.newaxis, :] * xm).sum(), need_a[m])
        penalty_ab += greater_equal((beta[np.newaxis, :] * xm).sum(), need_b[m])

    # ============================================================
    # モデル
    # ============================================================
    model = total_cost + coverage + penalty_one + penalty_ab

    # ============================================================
    # ソルバーの設定と結果の取得
    # ============================================================
    client = AmplifyAEClient()
    client.token = token
    client.parameters.time_limit_ms = timedelta(milliseconds=time_limit)  # タイムアウト

    with st.spinner('アニーリング中…'):
        # filter_solution=False：制約を満たさない解も返してもらい、どこが足りないかを表示する
        result = solve(model, client, filter_solution=False)
    if len(result) == 0:
        st.error('解が得られませんでした')
        st.stop()

    place = x.evaluate(result.best.values)  # 形は N × K（置く所が 1）
    st.session_state['place'] = np.round(place).astype(int)


# ============================================================
# 計算結果の確認
# ============================================================
if 'place' in st.session_state:
    place = st.session_state['place']

    # 市町村ごとに α・β・カバー率が必要量に届いているか
    rows = []
    for m in range(M):
        a_sum = (alpha * place[pm == m]).sum()
        b_sum = (beta * place[pm == m]).sum()
        rate = (covers[m] & (place[None, :, :] == 1)).any(axis=(1, 2)).mean()  # 覆われたマス目の割合
        ok = a_sum >= need_a[m] and b_sum >= need_b[m] and rate + 0.001 >= need_c[m]  # カバー率は 0.1 ポイントまで誤差
        rows.append({'市町村': muni_table['市町村'][m], '台数': int(place[pm == m].sum()),
                     'α': f'{a_sum:.0f} / {need_a[m]:.0f}', 'β': f'{b_sum:.0f} / {need_b[m]:.0f}',
                     'カバー率': f'{rate:.1%} / {need_c[m]:.0%}', '判定': '✅' if ok else '❌'})

    col3, col4, col5 = st.columns(3)
    with col3:
        st.metric('総コスト', f'{(cost * place).sum():,.0f}')
    with col4:
        st.metric('設置台数', f'{place.sum()} 台')
    with col5:
        st.metric('要求を満たした市町村', f"{sum(r['判定'] == '✅' for r in rows)} / {M}")

    # 罰金項のチェック：1つの地点に2台以上置いていないか
    count = place.sum(axis=1)
    if (count > 1).any():
        st.warning(f'1つの地点に2台以上置いた所が {(count > 1).sum()} か所あります（タイムアウトを長くしてみてください）')

    col6, col7 = st.columns([3, 2])

    with col6:
        st.write('🗺️センサーの配置')
        fig = draw_map(munis, rows, place, points, px, py, radius, sensor_table['名称'], grid)
        st.plotly_chart(fig, width='stretch')

    with col7:
        st.write('📋市町村ごとの達成状況')
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
        st.caption(f'カバー率は {grid} m × {grid} m のマス目で判定しています（QUBO の中も同じマス目）')

        st.write('📡置くセンサー')
        placed = [{'地点': points[i]['id'], '市町村': muni_table['市町村'][pm[i]], '種類': sensor_table['名称'][k],
                   'コスト': cost[k]} for i in range(N) for k in range(K) if place[i, k] == 1]
        st.dataframe(pd.DataFrame(placed), hide_index=True, width='stretch', height=300)
