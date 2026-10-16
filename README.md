# センサー配置最適化アプリ

量子アニーリング（Fixstars Amplify AE）で、8つの市町村にセンサーをどう置けば
α・βの必要量とカバー率を満たしつつ総コストを小さくできるかを計算する Streamlit アプリです。

## いちばん簡単な起動方法

Finder でこのフォルダ（Optimal-Sensor-Placement-in-Two-Dimensions）を開き、**`アプリを起動.command` をダブルクリック**します。
少し待つとブラウザが開くので、「QUBOを実行」を押してください。
止めるときは、一緒に開いたターミナルの画面を閉じます。

## VS Code で起動する方法

1. VS Code の「ファイル」→「フォルダーを開く」で、デスクトップの
   「Claude 量子アニーリング　センサー配置最適化」フォルダを開く
2. 「ターミナル」→「新しいターミナル」を開く
3. 次の2行を1行ずつ貼り付けて Enter

   ```
   cd Optimal-Sensor-Placement-in-Two-Dimensions
   ../.venv/bin/streamlit run app.py
   ```

4. ブラウザが開きます（開かないときは http://localhost:8501 を開く）
5. 止めるときはターミナルで `Ctrl + C`

`zsh: no such file or directory` と出たら、`cd Optimal-Sensor-Placement-in-Two-Dimensions` を忘れています。
ターミナルの行の左に `Optimal-Sensor-Placement-in-Two-Dimensions %` と出ていれば正しい場所です。

## ファイルの中身

| ファイル | 役割 |
|---|---|
| `app.py` | アプリ本体（データの用意 → 変数 → コスト関数 → 罰金項 → モデル → ソルバー → 結果の表示） |
| `helpers.py` | app.py から呼ぶ関数（カバー率のマス目づくり、カバー率の報酬の式、地図の描き方） |
| `data/data_transformed.json` | 市町村・候補地点・センサーのデータ（「QQG 資料とか」と同じもの） |
| `.streamlit/secrets.toml` | Amplify のアクセストークン（`AMPLIFY_TOKEN`）。git には入れない |
| `.streamlit/secrets.toml.example` | トークンの書き方の見本 |
| `requirements.txt` | 必要なライブラリ |

## 計算の初期設定

- マス目の大きさ 500 m（カバー率はマス目の中心が円に入るかで数える）
- 中央市のカバー率下限は 95%（元データは 100%）
- カバー率の重み λ_cov = 4（サイドバー下の「詳しい設定」）、タイムアウト 5 秒
  （この設定でほとんどの回で 8 市町村すべて達成、総コストはおよそ 6,400〜6,500）
- 制約（1地点1台、α・β の必要量）の重みは Amplify AE が自動で調整する

## 最初の準備（新しいパソコンで動かすとき）

```
python3 -m venv .venv
.venv/bin/pip install -r Optimal-Sensor-Placement-in-Two-Dimensions/requirements.txt
```

そのあと `.streamlit/secrets.toml.example` をコピーして `secrets.toml` にし、自分のトークンを書きます。
