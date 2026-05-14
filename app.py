from flask import Flask, render_template, request, redirect, url_for, session
from database import get_connection, initialize_database
import random
import string
from flask_socketio import SocketIO, emit
from flask_socketio import join_room

app = Flask(__name__)
app.secret_key = "Hello_Natehc"
socketio = SocketIO(app, async_mode="threading")
initialize_database()

words = [
    # Level 1 – easy
    [
        "Cat","DoG","Run","Jump","Fish","Tree","Rock","Moon","Star","Game",
        "Play","Time","Fast","Blue","Green","Smile","Happy","Train","Bread","Water",
        "Cloud","River","Stone","Plant","Chair","Table","Light","Sound","Power","Speed",
        "Dream","Laugh","Magic","Pixel","Frame","Track","Brush","Paper","Glass","Metal",
        "Clock","Drink","Sweet","Fruit","Music","Dance","World","Peace","Sharp","Quick",
        "Smart","Fresh","Clean","Shine","Focus"
    ],
    # Level 2 – mixed uppercase
    [
        "AppLe","BanAna","OranGe","PenCil","WinDow","GarDen","ButTon","PilLow","MarKet","YelLow",
        "PurPle","SilVer","RocKet","ForEst","IsLand","RabBit","TunNel","JunGle","PockEt","MirRor",
        "FloWer","PlaNet","RivEr","BasKet","CasTle","DraGon","SchOol","BriDge","CamEra","PapEr",
        "LetTer","TraVel","VacUum","PuzZle","ArtIst","EngIne","VillAge","HolIday","DiaMond","CryStal",
        "CotTon","BlanKet","LanTern","PicTure","WeaTher","ThunDer","SeaSon","TemPle","StaTion","BatTery"
    ],
    # Level 3 – uppercase + numbers
    [
        "AbunDant1","AbsoluTe2","AcadEmy3","AccurAcy4","AmbiTion5","AnalySis6","AnceStor7","ApparEnt8","ArguMent9","AttiTude1",
        "BounDary2","CaleNdar3","CapaCity4","CereMony5","CircUlar6","CollApse7","CombiNation8","CommuNity9","CompArison1","ComplAint2",
        "ConfiDence3","ConseQuence4","ConstRuction5","ConveNient6","CuriOsity7","DeciSion8","DemoCracy9","DeveLopment1","DimeNsion2","DiscOvery3",
        "EducaTion4","EffiCient5","EvolUtion6","FounDation7","FreqUency8","GeneRation9","HarMony1","HistOrical2","IdenTity3","ImagInation4",
        "IndePendent5","InduStry6","InforMation7","InspiRation8","InvesTment9","KnowLedge1","LandScape2","LiteRature3","ManaGement4","MotiVation5"
    ]
]

game_state = {}


# ─── BACKGROUND TASKS ───────────────────────────────────────────────

def run_timer(room_code):
    for i in range(30, 0, -1):
        socketio.emit("timer_tick", {"seconds_left": i}, to=room_code)
        socketio.sleep(1)
    end_round(room_code)


def run_countdown(room_code):
    for i in range(10, 0, -1):
        socketio.emit("countdown", {"seconds_left": i}, to=room_code)
        socketio.sleep(1)
    game_state[room_code]["round_status"] = "active"
    socketio.emit("round_start", {
        "word": game_state[room_code]["current_word"],
        "round": game_state[room_code]["current_round"]
    }, to=room_code)
    run_timer(room_code)


def end_round(room_code):
    game_state[room_code]["round_status"] = "between"
    players = game_state[room_code]["players"]

    # find round winner
    winner_id = max(players, key=lambda pid: players[pid]["round_score"])
    scores = [p["round_score"] for p in players.values()]
    is_draw = scores.count(max(scores)) > 1

    # update round_wins in database if not a draw
    if not is_draw:
        conn = get_connection()
        conn.execute(
            "UPDATE players SET rounds_win = rounds_win + 1 WHERE id = ?",
            (winner_id,)
        )
        conn.commit()
        conn.close()

    # build players data for browser
    players_data = [
        {"name": p["name"], "round_score": p["round_score"]}
        for p in players.values()
    ]

    socketio.emit("round_end", {
        "round_winner": None if is_draw else players[winner_id]["name"],
        "players": players_data
    }, to=room_code)

    current_round = game_state[room_code]["current_round"]

    if current_round < 3:
        game_state[room_code]["current_round"] += 1
        game_state[room_code]["players_ready"] = 0
        next_round = game_state[room_code]["current_round"]
        game_state[room_code]["current_word"] = game_state[room_code]["words"][next_round - 1][0]
        for pid in players:
            players[pid]["round_score"] = 0
            players[pid]["word_index"] = 0
    else:
        conn = get_connection()
        db = conn.cursor()
        room = db.execute(
            "SELECT id FROM rooms WHERE room_code = ?", (room_code,)
        ).fetchone()
        players_final = db.execute(
            "SELECT name, rounds_win FROM players WHERE room_id = ?",
            (room["id"],)
        ).fetchall()
        conn.execute(
            "UPDATE rooms SET room_status = ? WHERE room_code = ?",
            ("Ended", room_code)
        )
        conn.commit()
        conn.close()

        winner = max(players_final, key=lambda p: p["rounds_win"])
        all_wins = [p["rounds_win"] for p in players_final]
        overall_draw = all_wins.count(max(all_wins)) > 1

        socketio.emit("game_end", {
            "game_winner": None if overall_draw else winner["name"],
            "players": [dict(p) for p in players_final]
        }, to=room_code)


# ─── ROUTES ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create_room", methods=["POST"])
def create_room():
    name = request.form.get("name")
    room_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO rooms (room_code) VALUES (?)', (room_code,))
    room_id = cursor.lastrowid
    cursor.execute('INSERT INTO players (name, room_id) VALUES (?, ?)', (name, room_id))
    conn.commit()
    conn.close()

    session["name"] = name
    session["room_code"] = room_code
    session["is_host"] = 1
    return redirect(url_for("lobby", room_code=room_code))


@app.route("/joining_room", methods=["POST"])
def joining_room():
    name = request.form.get("name")
    room_code = request.form.get("room_code").upper()

    conn = get_connection()
    cursor = conn.cursor()

    room = cursor.execute(
        'SELECT id, room_status FROM rooms WHERE room_code = ?', (room_code,)
    ).fetchone()

    if room is None:
        conn.close()
        return render_template("error.html",
                        error_title="Room Not Found",
                        error_message="The room code you entered doesn't exist. Double-check it and try again.")

    if room["room_status"] == "Active":
        conn.close()
        return render_template("error.html",
                               error_title="Game Already Started",
                               error_message="This game is already in progress. Wait for the next round or create your own room.")

    if room["room_status"] == "Ended":
        conn.close()
        return render_template("error.html",
                               error_title="Game Already Ended",
                               error_message="This game has finished. Head back and create a new room to play again!")

    cursor.execute('INSERT INTO players (name, room_id) VALUES (?, ?)', (name, room["id"]))
    conn.commit()
    conn.close()

    session["name"] = name
    session["room_code"] = room_code
    session["is_host"] = 0
    return redirect(url_for("lobby", room_code=room_code))


@app.route("/lobby/<room_code>")
def lobby(room_code):
    if "name" not in session:
        return redirect(url_for("index"))
    return render_template("lobby.html", room_code=room_code, is_host=session["is_host"])


@app.route("/game/<room_code>")
def game(room_code):
    if "name" not in session:
        return redirect(url_for("index"))
    return render_template("game.html", room_code=room_code)


# ─── SOCKETIO EVENTS ────────────────────────────────────────────────

@socketio.on("join")
def on_join(data):
    room_code = data["room_code"]
    join_room(room_code)

    conn = get_connection()
    db = conn.cursor()
    room_id = db.execute("SELECT id FROM rooms WHERE room_code = ?", (room_code,)).fetchone()
    players = db.execute("SELECT * FROM players WHERE room_id = ?", (room_id["id"],)).fetchall()
    conn.close()

    emit("update_players", {"players": [dict(p) for p in players]}, to=room_code)


@socketio.on("start_game")
def on_start_game(data):
    room_code = data["room_code"]
    db = get_connection()
    room = db.execute("SELECT id FROM rooms WHERE room_code = ?", (room_code,)).fetchone()
    players = db.execute("SELECT * FROM players WHERE room_id = ?", (room["id"],)).fetchall()

    db.execute("UPDATE rooms SET room_status = ? WHERE room_code = ?", ("Active", room_code))
    db.commit()
    db.close()

    shuffled_words = [random.sample(round_pool, 10) for round_pool in words]
    game_state[room_code] = {
        "current_round": 1,
        "round_status": "waiting",
        "current_word": shuffled_words[0][0],
        "words": shuffled_words,
        "players": {
            p["id"]: {
                "name": p["name"],
                "word_index": 0,
                "round_score": 0
            } for p in players
        },
        "players_ready": 0
    }
    emit("redirect_to_game", {}, to=room_code)


@socketio.on("join_game")
def on_join_game(data):
    room_code = data["room_code"]
    join_room(room_code)

    # if round is active (e.g. player refreshed mid-round), rejoin silently
    if game_state[room_code]["round_status"] == "active":
        for pid, pdata in game_state[room_code]["players"].items():
            if pdata["name"] == session["name"]:
                current_round = game_state[room_code]["current_round"]
                word_index = pdata["word_index"]
                round_words = game_state[room_code]["words"][current_round - 1]
                current_word = round_words[word_index] if word_index < len(round_words) else None
                emit("round_start", {
                    "word": current_word or "⏳ Waiting for others...",
                    "round": current_round
                })
                return

    game_state[room_code]["players_ready"] += 1
    total_players = len(game_state[room_code]["players"])

    if game_state[room_code]["players_ready"] == total_players:
        socketio.start_background_task(run_countdown, room_code)


@socketio.on("submit_word")
def on_submit_word(data):
    room_code = data["room_code"]
    word = data["word"]

    if game_state[room_code]["round_status"] != "active":
        return

    player_id = None
    for pid, pdata in game_state[room_code]["players"].items():
        if pdata["name"] == session["name"]:
            player_id = pid
            break

    current_round = game_state[room_code]["current_round"]
    word_index = game_state[room_code]["players"][player_id]["word_index"]
    round_words = game_state[room_code]["words"][current_round - 1]
    current_word = round_words[word_index]

    is_correct = word == current_word
    if is_correct:
        game_state[room_code]["players"][player_id]["round_score"] += 10

    game_state[room_code]["players"][player_id]["word_index"] += 1
    new_index = game_state[room_code]["players"][player_id]["word_index"]
    next_word = round_words[new_index] if new_index < len(round_words) else None

    emit("word_result", {
        "correct": is_correct,
        "next_word": next_word,
        "score": game_state[room_code]["players"][player_id]["round_score"]
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)