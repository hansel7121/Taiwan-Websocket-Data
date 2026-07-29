import clr
import sys
import builtins
import tradecomPy
from System import UInt16
from Intelligence import CreditQType

"""
指令                    功能                            參數            說明及範例
-----------------------------------------------------------------------------------------
CONNECT                 連線
LOGIN                   登入                            ID,PW           Ex: LOGIN,A123456789,0000 
LOGOUT                  登出
EXIT                    關閉程式
ORDER                   下單                            見程式備註       Ex: 下單--ORDER,9228,1234567,2883,O,0,0,0,S,5,12.5, , ,R
		                                                                    刪單--ORDER,9228,1234567,2883,C,0,0,0,B,0,0, ,Y0003,R
                                                                            改價--ORDER,9228,1234567,2883,P,0,0,0,B,2,12.8, ,Y0007,R
		                                                                    改量--ORDER,9228,1234567,2883,Q,0,0,0,B,2,12.5, ,Y0004,R
4302                    當日交割金額試算查詢                              EX: 4302,9228,1234567,2883,
4304                    當日交割金額_沖銷明細(非當沖)查詢                  EX:4304,D,9228,0005082,2883,Y002L,
4306                    交割金額查詢(3日)查詢                             EX:4306,S,9228,1234567,
4308                    庫存損益及即時維持率試算查詢                       EX:4308,M,9228,1234567,,A,
4310                    證券庫存彙總查詢                                  EX:4310,A,9228,1234567, ,
4312                    證券對帳單查詢                                    EX:4312,M,9228,1234567, , ,20220901,20221109,0,
4314                    已實現損益查詢                                    EX:4314,M,9228,1234567, , ,20220901,20221110,0,
4033                    資券餘額查詢                                      EX:4033,9228,S,2890, 
"""

tradecomPy.initialize()

#command mode, 格式為: 指令,參數1,參數2,參數3........................
inputstr = input('請輸入指令:')
args = inputstr.split(',')
command=args[0]

while (command!="EXIT"):      
    if command=="CONNECT":  
        #連線
        host='itradetest.kgi.com.tw'
        port=UInt16(8000)
        timeout=5000
        tradecomPy.tradeCom.Connect(host, port, timeout)
    if command=="LOGIN":  
        #登入    
        #host='iquotetest.kgi.com.tw'
        #是否註冊即時回報
        tradecomPy.tradeCom.AutoSubReportSecurity=True ;  
        #是否回補回報
        tradecomPy.tradeCom.AutoRecoverReportSecurity=True;   
        uid=args[1]
        pwd=args[2]                
        tradecomPy.tradeCom.Login(uid, pwd, ' ')
    elif command=="LOGOUT":
        #登出
        tradecomPy.tradeCom.Logout()
    elif command=="ORDER":  
        #下單        
        #券商代碼
        brokerid=args[1]
        #交易帳號
        account=args[2]
        #股票代碼
        stockid=args[3]
        #委託別: O.下單 C.刪單 P.改量 Q.改價 
        otype=args[4]
        #交易盤別: 0.整股 1.零股 2.定價 3.鉅額 4.盤中零股
        oLot=args[5]
        #委託種類: 0.現股 3.自資 4.自券 5.借券賣出 6.借券賣出(盤下限制豁免) 7.當沖融資 8.當沖融券 9.現先賣
        oclass=args[6]
        #價格旗標: 0.限價 1.跌停 2.平盤 3.漲停 4.巿價
        pflag=args[7]
        #買賣別 B:買 S:賣
        bs=args[8]
        #交易數量
        qty=args[9]
        #委託價格
        prz=args[10]       
        #營業員代碼, 空白為不指定
        agend=args[11]
        #委託書號,刪改單時要帶,下單可用空白
        orderno=args[12]
        #委託條件 : R:ROC I:IOC F:FOK
        tif=args[13]
        
        tradecomPy.SendOrder(brokerid, account, stockid, otype, oLot, oclass, pflag, bs, qty, prz, agend, orderno, tif)
    elif command=="4302":  
        #4302 當日交割金額試算查詢 
        ##ftype 查詢類別--M:股票+交易類別彙總   D:明細  S:台幣彙總(不含外幣)   SS:彙總多筆(客戶+幣別)
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        rtn = tradecomPy.tradeCom.RetrieveWsSettleAmtTrial(ftype, brokerid, account, stockid)
        if (rtn == -1): print("無當日交割金額試算查詢權限!")
    elif command=="4304":  
        #4304 當日交割金額_沖銷明細(非當沖)查詢 
        ##ftype 查詢類別--D:明細
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        #委託書號
        orderno=args[5]
        rtn = tradecomPy.tradeCom.RetrieveWsSettleAmtDetail(ftype, brokerid, account, stockid, orderno)
        if (rtn == -1): print("無當日交割金額_沖銷明細(非當沖)查詢權限!")
    elif command=="4306":          
        #4306 交割金額查詢(3日)查詢
        ##ftype 查詢類別--S:台幣 含當日即時應收付金額試算 S1:台幣 若未結帳則不計算當日應收付金額 SS:台外幣 含當日即時應收付金額試算 SS1:台外幣  若未結帳則不計算當日應收付金額
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        rtn = tradecomPy.tradeCom.RetrieveWsSettleAmt(ftype, brokerid, account) 
        if (rtn == -1): print("無交割金額查詢(3日)查詢權限!")
    elif command=="4308":          
        #4308 庫存損益及即時維持率試算查詢
        ##ftype 查詢類別--M:股票+交易類別小計  M1:股票+交易類別小計  D:明細 (現資券合併)  S:帳號彙總成1筆(台幣)   SS:帳號彙總成多筆 (客戶+幣別) D1:明細 (資券分開無現股)
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        #資料類別 A:全部(今日留存庫存的未實現損益)  A0:現股(今日留存庫存的未實現損益,含現賣庫存 ) A3:融資(今日留存庫存的未實現損益)
        #        A4:融券 (今日留存庫存的 未實現損益)  B0:現股當日新增(今日新增庫存,含現賣庫存)   B4:融券當日新增(今日新增庫存)  S:現賣
        dtype=args[5]
        rtn = tradecomPy.tradeCom.RetrieveWsInventory(ftype, brokerid, account, stockid, dtype )
        if (rtn == -1): print("無庫存損益及即時維持率試算查詢權限!")
    elif command=="4310":          
        #4310 證券庫存彙總查詢, 若庫存資料量大,會分多筆送回, 故須自行判斷是否傳送完畢(NowCount = TotalCount)
        ##ftype 查詢類別--A:現股以張數顯示 B:現股以股數顯示
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        rtn = tradecomPy.tradeCom.RetrieveWsInventorySum(ftype, brokerid, account, stockid)
        if (rtn == -1): print("無證券庫存彙總查詢權限!")
    elif command=="4312":     
        #4312 證券對帳單查詢
        ##ftype 查詢類別--D:明細  M:日彙總
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        #資料類別 T:交易  N:非交易  ' ':全部
        dtype=args[5]
        #查詢日期起迄 OR 查詢天數 (擇一), 查詢日期起迄填dateb, datee, 查詢天數填datee, qdays(從日期前qdays天)
        #查詢日期起日
        dateb=args[6]
        #查詢日期迄日
        datee=args[7]
        #查詢日期迄日前N天
        qdays=int(args[8])
        rtn = tradecomPy.tradeCom.RetrieveWsBalanceStatement(ftype, brokerid, account, stockid, dtype, dateb, datee, qdays);
        if (rtn == -1): print("無證券對帳單查詢權限!")
    elif command=="4314":     
        #4314 已實現損益查詢
        ##ftype 查詢類別--M:股票+交易類別彙總   D:明細  S:台幣彙總(不含外幣)   SS:彙總多筆(客戶+幣別)
        ftype=args[1]
        #券商代碼
        brokerid=args[2]
        #交易帳號
        account=args[3]
        #股票代碼
        stockid=args[4]
        #資料類別
        dtype=''
         #查詢日期起迄 OR 查詢天數 (擇一), 查詢日期起迄填dateb, datee, 查詢天數填datee, qdays(從日期前qdays天)
        #查詢日期起日
        dateb=args[6]
        #查詢日期迄日
        datee=args[7]
        #查詢日期迄日前N天
        qdays=int(args[8])
        rtn = tradecomPy.tradeCom.RetrieveWsRealizePL(ftype, brokerid, account, stockid, dtype, dateb, datee, qdays);
        if (rtn == -1): print("無已實現損益查詢權限!")
    elif command=="4033": 
        #4033 資券餘額查詢 
        #券商代碼
        brokerid=args[1]
        #類別 S:股票, I:類股
        qtype=args[2]
        if (qtype=='I'):
            queryType=CreditQType.Idx
        else:        
            queryType=CreditQType.Stk        
        #股票代碼
        stockid=args[3]
        rtn = tradecomPy.tradeCom.RetrieveTSECreditInfo(brokerid, queryType, stockid);
        if (rtn == -1): print("無資券餘額查詢權限!")
    inputstr = ''
    while (len(inputstr)<4):   
        inputstr = input('***請輸入指令:')
    
    args = inputstr.split(",")    
    command=args[0]

tradecomPy.tradeCom.Dispose()
