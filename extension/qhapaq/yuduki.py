import unittest
import sys
sys.path.append("/home/shiku/AI/shogi/bin/Ayane/source/shogi")
import Ayane as ayane
import time

class YudukiServer(ayane.AyaneruServer):
    """
    ユヅキサーバ 対局の細かい願いを叶えてくれる
    judge ... 勝ち負けの判別に特殊処理を入れる。最弱将棋エンジン探索などに使う
    """
    def __init__(self, judge=None):
        super(YudukiServer, self).__init__()
        self.judge = judge
        
    # 対局スレッド
    def _AyaneruServer__game_worker(self):
        # judge関数を呼べるようにするためだけに継承している。とても美しくない
        while self.game_ply < self.moves_to_draw:
            if self.judge is not None:
                judge(self)

            # 手番側に属するエンジンを取得する
            # ※　flip_turn == Trueのときは相手番のほうのエンジンを取得するので注意。
            engine = self.engine(self.side_to_move)
            engine.usi_position(self.sfen)

            # 現在の手番側["1p" or "2p]の時間設定
            byoyomi_str = "byoyomi" + self.player_str(self.side_to_move)
            inctime_str = "inc"     + self.player_str(self.side_to_move)
            inctime = self._AyaneruServer__time_setting[inctime_str]

            # inctimeが指定されていないならbyoymiを付与
            if inctime == 0:
                byoyomi_or_inctime_str = "byoyomi {0}".format(self._AyaneruServer__time_setting[byoyomi_str])
            else:
                byoyomi_or_inctime_str = "binc {0} winc {1}".\
                    format(self._AyaneruServer__time_setting["inc"+self.player_str(ayane.Turn.BLACK)], self._AyaneruServer__time_setting["inc"+self.player_str(ayane.Turn.WHITE)])
            
            start_time = time.time()
            engine.usi_go_and_wait_bestmove("btime {0} wtime {1} {2}".format(\
                self.rest_time(ayane.Turn.BLACK), self.rest_time(ayane.Turn.WHITE) , byoyomi_or_inctime_str))
            end_time = time.time()

            # 使用した時間を1秒単位で繰り上げて、残り時間から減算
            # プロセス間の通信遅延を考慮して300[ms]ほど引いておく。(秒読みの場合、どうせ使い切るので問題ないはず..)
            # 0.3秒以内に指すと0秒で指したことになるけど、いまのエンジン、詰みを発見したとき以外そういう挙動にはなりにくいのでまあいいや。
            elapsed_time = (end_time - start_time) - 0.3 # [ms]に変換
            elapsed_time = int(elapsed_time + 0.999) * 1000
            if elapsed_time < 0:
                elapsed_time = 0

            # 現在の手番を数値化したもの。1P側=0 , 2P側=1
            int_turn = self.player_number(self.side_to_move)
            self._AyaneruServer__rest_time[int_turn] -= int(elapsed_time)
            if self._AyaneruServer__rest_time[int_turn] < -2000: # -2秒より減っていたら。0.1秒対局とかもあるので1秒繰り上げで引いていくとおかしくなる。
                self.game_result = ayane.GameResult.from_win_turn(self.side_to_move.flip())
                self._AyaneruServer__game_over()
                # 本来、自己対局では時間切れになってはならない。(計測が不確かになる)
                # 警告を表示しておく。
                print("Error! : player timeup") 
                return
            # 残り時間がわずかにマイナスになっていたら0に戻しておく。
            if self._AyaneruServer__rest_time[int_turn] < 0:
                self._AyaneruServer__rest_time[int_turn] = 0

            bestmove = engine.think_result.bestmove
            if bestmove == "resign":
                # 相手番の勝利
                self.game_result = ayane.GameResult.from_win_turn(self.side_to_move.flip())
                self._AyaneruServer__game_over()
                return 
            if bestmove == "win":
                # 宣言勝ち(手番側の勝ち)
                # 局面はノーチェックだが、まあエンジン側がバグっていなければこれでいいだろう)
                self.game_result = ayane.GameResult.from_win_turn(self.side_to_move)
                self._AyaneruServer__game_over()
                return

            self.sfen = self.sfen + " " + bestmove
            self.game_ply += 1

            # inctime分、時間を加算
            self._AyaneruServer__rest_time[int_turn] += inctime
            self.side_to_move = self.side_to_move.flip()
            # 千日手引き分けを処理しないといけないが、ここで判定するのは難しいので
            # max_movesで抜けることを期待。

            if self._AyaneruServer__stop_thread:
                # 強制停止なので試合内容は保証されない
                self.game_result = ayane.GameResult.STOP_GAME
                return 

        # 引き分けで終了
        self.game_result = ayane.GameResult.MAX_MOVES
        self._AyaneruServer__game_over()


def relay_by_ply(engine, posstr):
    if len(posstr.split(" ")) > 30:
        # print("relay")
        return True
    return False
        
class UsiEngineRelay(ayane.UsiEngine):
    """
    リレー形式で戦うエンジン。ルリグが対局を引き継いでくれる
    デフォルトでusi1が戦うが、特定の条件を満たすとusi2に指し手が変わる
    条件はユーザが外から入れる。
    switch_xxx ... usi2を使うか否かを決める。boolを返す。引数はこのエンジン自体とstr
    """
    def __init__(self, usi1, usi2, switch_command=None, switch_pos=None, switch_go=None):
        super(UsiEngineRelay, self).__init__()
        self.switch_command = switch_command
        self.switch_pos = switch_pos
        self.switch_go = switch_go
        self.usi1 = usi1
        self.usi2 = usi2
        self.usi_to_use = self.usi1

    def connect(self, engine_path: str):
        print("connect is invalid function for UsiEngineRelay!!")
        
    def send_command(self, message : str):
        if self.switch_command is not None:
            if self.switch_command(self, message):
                self.usi_to_use = self.usi2
            else:
                self.usi_to_use = self.usi1
            
        self.usi_to_use.send_command(message)

    def is_connected(self):
        return self.usi_to_use.is_connected()
        
    def disconnect(self):
        self.usi1.disconnect()
        self.usi2.disconnect()
        self.engine_state = ayane.UsiEngineState.Disconnected

        
    def wait_for_state(self, state : ayane.UsiEngineState):
        self.usi_to_use.wait_for_state(state)

    def get_moves(self) -> str:
        return self.usi_to_use.get_moves()

    def get_side_to_move(self) -> ayane.Turn:
        return self.usi_to_use.get_side_to_move()

    def usi_position(self,sfen : str):
        if self.switch_pos is not None:
            if self.switch_pos(self, sfen):
                self.usi_to_use = self.usi2
            else:
                self.usi_to_use = self.usi1
        self.usi_to_use.send_command("position " + sfen)

    def usi_go(self,options:str):
        if self.switch_go is not None:
            if self.switch_go(self, options):
                self.usi_to_use = self.usi2
            else:
                self.usi_to_use = self.usi1

        self.usi_to_use.think_result = UsiThinkResult()
        self.usi_to_use.send_command("go " + options)
        self.think_result = self.usi_to_use.think_result
        
    def usi_go_and_wait_bestmove(self,options:str):
        if self.switch_go is not None:
            if self.switch_go(self, options):
                self.usi_to_use = self.usi2
            else:
                self.usi_to_use = self.usi1

        self.usi_to_use.usi_go(options)
        self.usi_to_use.wait_bestmove()
        self.think_result = self.usi_to_use.think_result

    def usi_stop(self):
        self.usi_to_use.send_command("stop")

    def wait_bestmove(self):
        with self.usi_to_use.__state_changed_cv:
            self.usi_to_use.__state_changed_cv.wait_for(lambda : self.usi_to_use.think_result.bestmove is not None)

    def __send_command_and_getline(self,command:str) -> str:
        print("__send_command is invalid function for UsiEngineRelay!!")
        
    def __read_worker(self):
        print("__read_worker is invalid function for UsiEngineRelay!!")
        
    def __write_worker(self):
        print("__write_worker is invalid function for UsiEngineRelay!!")


def test_analysis():
    unit = unittest.TestCase()
    
    usi1 = ayane.UsiEngine()
    #    usi.debug_print = True
    usi1.set_engine_options({"Hash":"128","Threads":"1","NetworkDelay":"0","NetworkDelay2":"0","MaxMovesToDraw":"256" \
                , "MinimumThinkingTime":"0"})
    usi1.connect("YaneuraOu-tnk")

    usi2 = ayane.UsiEngine()
    #    usi.debug_print = True
    usi2.set_engine_options({"Hash":"128","Threads":"1","NetworkDelay":"0","NetworkDelay2":"0","MaxMovesToDraw":"256" \
                , "MinimumThinkingTime":"0"})
    usi2.connect("YaneuraOu-tnk")

    
    ur = UsiEngineRelay(usi1, usi2, switch_pos = relay_by_ply)
    ur.usi_position("startpos moves 7g7f")

    moves = ur.get_moves()
    unit.assertEqual(moves , "1c1d 2c2d 3c3d 4c4d 5c5d 6c6d 7c7d 8c8d 9c9d 1a1b 9a9b 3a3b 3a4b 7a6b 7a7b 8b3b 8b4b 8b5b 8b6b 8b7b 8b9b 4a3b 4a4b 4a5b 5a4b 5a5b 5a6b 6a5b 6a6b 6a7b")

    # 現在の局面の手番を得る
    turn = ur.get_side_to_move()
    unit.assertEqual(turn , ayane.Turn.WHITE)
    
    # multipv 4で探索させてみる
    # 2秒思考して待機させる。
    ur.send_command("multipv 4")
    ur.usi_go_and_wait_bestmove("btime 0 wtime 0 byoyomi 2000")
    
    # 思考内容を表示させてみる。
    print("=== UsiThinkResult ===\n" + ur.usi_to_use.think_result.to_string())

    # エンジンを切断
    ur.disconnect()
    unit.assertEqual( ur.engine_state , ayane.UsiEngineState.Disconnected)

def test_yuduki_battle():
    sv = ayane.AyaneruServer()
    sv.error_print = True
    # sv = ayane.AyaneruSv()
    usi3 = ayane.UsiEngine()
    #    usi.debug_print = True
    usi3.set_engine_options({"Hash":"1024","EvalDir":"Kristallweizen", "Threads":"4","NetworkDelay":"0","NetworkDelay2":"0","ResignValue" : "2019","MaxMovesToDraw":"256" \
                , "MinimumThinkingTime":"0"})
    usi3.connect("YaneuraOu-tnk")

    usi1 = ayane.UsiEngine()
    usi1.set_engine_options({"Hash":"1024","EvalDir":"eval", "Threads":"4","NetworkDelay":"0","NetworkDelay2":"0","ResignValue" : "2019","MaxMovesToDraw":"256" \
                , "MinimumThinkingTime":"0"})
    usi1.connect("YaneuraOu-tnk")

    
    usi2 = ayane.UsiEngine()
    usi2.set_engine_options({"Hash":"1024","EvalDir":"Kristallweizen","Threads":"4","NetworkDelay":"0","NetworkDelay2":"0","ResignValue" : "2019","MaxMovesToDraw":"256" \
                , "MinimumThinkingTime":"0"})
    usi2.connect("YaneuraOu-tnk")

        
    ur = UsiEngineRelay(usi1, usi2, switch_pos = relay_by_ply)
    
    sv.engines[0] = ur
    sv.engines[1] = usi3
    # sv.engines[1] = usi2 # nnue vs kppt 0.1sec 248-232
    
    # 持ち時間設定。
    sv.set_time_setting("byoyomi 1000")                 # 1手0.2秒
    # sv.set_time_setting("time 1000 inc 2000")        # 1秒 + 1手2秒

    win1p = 0
    win2p = 0
    for i in range(114514):
        # これで対局が開始する
        
        if i % 2 == 0:
            sv.flip_turn = False
        else:
            sv.flip_turn = True
        
        # 対局が終了するのを待つ
        sv.game_start()
        while not sv.game_result.is_gameover():
            time.sleep(1)

        # 対局棋譜の出力
        if sv.game_result == ayane.GameResult.BLACK_WIN:
            if i % 2 == 0:
                win1p += 1
            else:
                win2p += 1
        elif sv.game_result == ayane.GameResult.WHITE_WIN:
            if i % 2 == 0:
                win2p += 1
            else:
                win1p += 1
        print("game sfen = " + sv.sfen)
        print("game_result = " + str(sv.game_result))
        print("stat", win1p, "-", win2p)
            
    sv.terminate()

if __name__=='__main__':
    test_yuduki_battle()
    # test_analysis()
