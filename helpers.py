# app.py から使う「下ごしらえ」と「表示」の関数をまとめたファイル
#   app.py にはお手本と同じ流れ（データ → 変数 → コスト関数 → 罰金項 → モデル → ソルバー → 結果確認）だけを残し、
#   長くなる計算や地図の描き方はここに置いている
import numpy as np
import plotly.graph_objects as go


# ============================================================
# カバー率を数えるマス目をつくる
# ============================================================
def make_covers(munis, px, py, pm, radius, grid, cross):
    """市町村ごとに「どのマス目を、どの地点のどの種類のセンサーが覆うか」の表をつくる

    返すもの: covers（市町村ごとのリスト）
      covers[m][g, i, k] = True なら、市町村 m の g 番目のマス目を、地点 i に置いた種類 k のセンサーが覆う
    """
    covers = []
    for m, muni in enumerate(munis):
        # ① 市町村を囲む四角の中に、grid m ごとにマス目の中心点を並べる
        poly = np.array(muni['polygon_vertices'])
        gx, gy = np.meshgrid(np.arange(poly[:, 0].min(), poly[:, 0].max(), grid),
                             np.arange(poly[:, 1].min(), poly[:, 1].max(), grid))
        gx, gy = gx.ravel(), gy.ravel()

        # ② 市町村の境界の内側にある点だけ残す（レイキャスティング法：点から右へ伸ばした線が境界と奇数回交われば内側）
        inside = np.zeros(len(gx), dtype=bool)
        for j in range(len(poly)):
            (x1, y1), (x2, y2) = poly[j - 1], poly[j]
            inside ^= ((y1 > gy) != (y2 > gy)) & (gx < (x2 - x1) * (gy - y1) / (y2 - y1 + 1e-12) + x1)
        gx, gy = gx[inside], gy[inside]

        # ③ マス目と候補地点の距離を測り、センサーの半径以内なら「覆う」
        dist = np.sqrt((gx[:, None] - px[None, :]) ** 2 + (gy[:, None] - py[None, :]) ** 2)
        if not cross:
            dist[:, pm != m] = np.inf  # はみ出しを数えないときは、他の市町村のセンサーは覆わないことにする
        covers.append(dist[:, :, None] <= radius[None, None, :])
    return covers


# ============================================================
# カバー率の報酬（コスト関数の一部）
# ============================================================
def coverage_reward(x, covers, need_c, lam_cov):
    """マス目が覆われるほど得をする（値が小さくなる）項をつくる

    考え方：
      1つのマス目について、そのマス目を覆えるセンサーが 1台でも置かれたら −1 点にしたい。
      ただし QUBO では「1台でも」をそのまま書けないので、近い形として
          −（覆っている台数） ＋ 0.5 ×（覆っている2台の組の数）
      を使う。1台なら −1、2台なら −2＋0.5＝−1.5 となり、たくさん重ねても得が増えにくくなる。

    これを全部のマス目で足し合わせると、
      x[i, k] 1つにつく係数        ＝「そのセンサーが覆うマス目の数」
      x[i, k] と x[i', k'] の組の係数 ＝「2台の両方が覆うマス目の数」
    になるので、マス目を1つずつ足す代わりに、この数を数えてまとめて式にしている。
    """
    N, K = x.shape
    xf = x.flatten()  # x を1列に並べたもの（j = i * K + k 番目が x[i, k]）
    reward = 0
    for m in range(len(covers)):
        C = covers[m].reshape(len(covers[m]), N * K).astype(float)  # マス目 × センサー の 0/1 の表
        one = C.sum(axis=0)  # センサー j が覆うマス目の数
        both = C.T @ C       # センサー j と l の両方が覆うマス目の数
        w = lam_cov * need_c[m] / len(C)  # 必要なカバー率が高い市町村ほど重く、マス目の数で割って市町村の大きさをそろえる
        reward += -w * (one * xf).sum()
        for j, l in zip(*np.nonzero(np.triu(both, k=1))):
            reward += w * 0.5 * both[j, l] * xf[j] * xf[l]
    return reward


# ============================================================
# 地図を描く
# ============================================================
def draw_map(munis, rows, place, points, px, py, radius, sensor_names, grid):
    """市町村の境界、置いたセンサーとその範囲の円、置かなかった候補地点を地図に描く"""
    fig = go.Figure()
    colors = ['red', 'orange', 'royalblue', 'green', 'purple']

    # 市町村の境界（要求を満たしていれば緑、満たしていなければ赤）
    for m, muni in enumerate(munis):
        poly = np.array(muni['polygon_vertices'] + [muni['polygon_vertices'][0]]) / 1000
        fig.add_trace(go.Scatter(x=poly[:, 0], y=poly[:, 1], mode='lines', line=dict(color='gray', width=1),
                                 fill='toself', fillcolor='rgba(0,150,0,0.05)' if rows[m]['判定'] == '✅' else 'rgba(255,0,0,0.1)',
                                 showlegend=False, hoverinfo='skip'))
        fig.add_annotation(x=poly[:, 0].mean(), y=poly[:, 1].mean(), text=rows[m]['判定'] + rows[m]['市町村'],
                           showarrow=False, bgcolor='rgba(255,255,255,0.85)',
                           font=dict(color='black', size=13, weight='bold'))  # 暗いテーマでも読めるよう黒い文字にする

    # 置いたセンサーと有効範囲の円
    t = np.linspace(0, 2 * np.pi, 40)
    for k in range(len(radius)):
        chosen = np.nonzero(place[:, k])[0]
        for i in chosen:
            fig.add_trace(go.Scatter(x=(px[i] + radius[k] * np.cos(t)) / 1000, y=(py[i] + radius[k] * np.sin(t)) / 1000,
                                     mode='lines', fill='toself', line=dict(color=colors[k], width=1),
                                     opacity=0.2, showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=px[chosen] / 1000, y=py[chosen] / 1000, mode='markers',
                                 marker=dict(size=10, color=colors[k], line=dict(color='white', width=1)),
                                 name=sensor_names[k], text=[points[i]['id'] for i in chosen]))

    # 選ばれなかった候補地点
    empty = np.nonzero(place.sum(axis=1) == 0)[0]
    fig.add_trace(go.Scatter(x=px[empty] / 1000, y=py[empty] / 1000, mode='markers',
                             marker=dict(size=6, color='lightgray'), name='候補地点（置かない）',
                             text=[points[i]['id'] for i in empty]))

    # 背景にカバー率を数えるマス目と同じ間隔の薄いグリッド線を引く（座標は km なので grid / 1000）
    #   目盛りの数字はそのままにして、細かいグリッド（minor）だけマス目の間隔にする
    grid_line = dict(showgrid=True, gridcolor='rgba(0,0,0,0.15)', zeroline=False,
                     minor=dict(dtick=grid / 1000, showgrid=True, gridcolor='rgba(0,0,0,0.03)'))
    fig.update_layout(height=650, plot_bgcolor='white', legend=dict(orientation='h'),
                      xaxis=dict(title='x (km)', scaleanchor='y', **grid_line), yaxis=dict(title='y (km)', **grid_line))
    return fig
