import clr
import sys
import builtins
from System import Decimal as CSDecimal
from System import UInt16
from System import Int64

assembly_path = r"C:\Program Files\Python37\code"
sys.path.append(assembly_path)

clr.AddReference("Package")      #必要引用dll
clr.AddReference("PushClient")   #必要引用dll
clr.AddReference("TradeCom")     #必要引用dll
from Package import PackageBase
from Package import P001503    
from Smart import TaiFexCom
from Intelligence import PushClient
from Intelligence import DT 
from Intelligence import Security_OrdType
from Intelligence import Security_Lot
from Intelligence import Security_Class
from Intelligence import Security_PriceFlag
from Intelligence import SIDE_FLAG
from Intelligence import TIME_IN_FORCE
from Intelligence import COM_STATUS
from Intelligence import RECOVER_STATUS

#接收KGI QuoteCom API status event
def onTradeGetStatus(sender, status, msg):
    smsg = ' '

    ##if (status!=COM_STATUS.ACK_REQUESTID):   
    ##    smsg = bytes(msg).decode('UTF-8','strict')		

    if (status==COM_STATUS.CONNECT_READY):        
        print("STATUS:CONNECT_READY:["+smsg+"]")
    elif (status==COM_STATUS.CONNECT_FAIL):
        print("STATUS:CONNECT_FAIL:["+smsg+"]")
    elif (status==COM_STATUS.SUBSCRIBE):
        print("STATUS:SUBSCRIBE:["+smsg+"]")
    elif (status==COM_STATUS.DISCONNECTED):
        print("STATUS:DISCONNECTED:["+smsg+"]")
    elif (status==COM_STATUS.LOGIN_READY):
        print("STATUS:LOGIN_READY:["+smsg+"]")		
    elif (status==COM_STATUS.LOGIN_FAIL):
        print("STATUS:LOGIN_FAIL:["+smsg+"]")				
    elif (status==COM_STATUS.LOGIN_UNKNOW):
        print("STATUS:LOGIN_UNKNOW:["+smsg+"]")						
    elif (status==COM_STATUS.UNSUBSCRIBE):
        print("STATUS:UNSUBSCRIBE:["+smsg+"]")								
    elif (status==COM_STATUS.ACK_REQUESTID):   
        #python_bytes = bytes(msg)        
        #reqid = int.from_bytes(python_bytes[0:8], "little")    
        #print("STATUS:ACK_REQUESTID, RID={rid}]".format(rid=reqid)) 
        print("STATUS:ACK_REQUESTID")								
    elif (status==COM_STATUS.ACCTCNT_NOMATCH):				
        print("STATUS:ACCTCNT_NOMATCH:["+smsg+"]")						    
    elif (status==COM_STATUS.NOVALIDCERT):				
        print("STATUS:NOVALIDCERT:["+smsg+"]")			

    return    

def OnRecoverStatus(sender, Topic, status, RecoverCount):
    if (status==RECOVER_STATUS.RS_DONE):        
        #回補資料結束
        if (RecoverCount==0):
            print("結束回補 Topic:["+Topic+"]");
        else: 
            print("結束回補 Topic=[{tp}], 筆數=[{count}]".format(tp=Topic, count=RecoverCount))
    elif (status==RECOVER_STATUS.RS_BEGIN):       
        #開始回補資料
        print("開始回補 Topic:["+Topic+"]");

    return

def onTradeRcvMessage(sender, pkg):       
    print("onTradeRcvMessage DT=[{dt}]".format(dt=pkg.DT))

    if (pkg.DT==DT.LOGIN): 
        #登入回覆  
        if (pkg.Code==0):
            print("登入成功")
        else:
            errmsg=tradeCom.GetMessageMap(pkg.Code);
            print("登入失敗 CODE=[{code}], MSG=[{msg}]".format(code=pkg.Code, msg=errmsg))
    elif (pkg.DT==DT.NOTICE): 
        #公告
        print("公告=[{msg}]".format(msg=pkg.ToLog()))
    elif (pkg.DT==DT.SECU_ORDER_ACK or pkg.DT==DT.SECU_ORDER_ACK_N): 
        #委託收單回覆
        if (pkg.ErrorCode==0):
            print("收單回覆 RequestId=[{rid}], CNT=[{cnt}]".format(rid=pkg.RequestId, cnt=pkg.CNT))
            ridDict[pkg.CNT]=pkg.RequestId;
        else:
            errmsg=tradeCom.GetMessageMap(pkg.ErrorCode);
            print("收單回覆 CODE=[{code}], MSG=[{msg}]".format(code=pkg.ErrorCode, msg=errmsg))
    elif (pkg.DT==DT.SECU_ORDER_RPT): 
        #委託回報
        #"綜合帳戶", "營業員代碼",                                              "成交價格", "成交數量", "市場成交序號" 
        # p4011.SubAccount, p4011.OmniAccount, p4011.AgentId,   p4011.Price, p4011.DealQty, p4011.MarketNo, p4011.ReportTimeN, p4011.CNTN, p4011.ChannelN, p4011.PriceFlagN.ToString(), p4011.TimeInForceN.ToString(), p4011.PriceN, p4011.DealQtyN, p4011.AvgPriceN, p4011.SumQtyN, p4011.MarketNoN };
        if pkg.CNTN in ridDict.keys():
            requestId=ridDict[pkg.CNTN]
            print("委託回報--網路單號=[{rid}],電子單號=[{cnt}], 委託書號=[{ordNo}]".format(rid=requestId, cnt=pkg.CNTN, ordNo=pkg.OrderNo))
        else:
            requestId=0
            print("委託回報--電子單號=[{cnt}], 委託書號=[{ordNo}]".format(cnt=pkg.CNTN, ordNo=pkg.OrderNo))

        print("委託回報 CNT=[{cnt}]-->requestId=[{rid}]".format(cnt=pkg.CNTN, rid=requestId))
        print("委託回報--網路單號=[{rid}],電子單號=[{cnt}], 委託書號=[{ordNo}]".format(rid=requestId, cnt=pkg.CNTN, ordNo=pkg.OrderNo))
        print("委託回報--委託書號=[{OrderNo}],委託型態=[{OrderFunc}],帳號=[{BrokerId}{Account}],回報時間=[{ReportTime}]".format(OrderNo=pkg.OrderNo, OrderFunc=pkg.OrderFunc, BrokerId=pkg.BrokerId, Account=pkg.Account,ReportTime=pkg.ReportTime))
        print("委託回報--委託書號=[{OrderNo}],市場別=[{Market}],商品代碼=[{StockID}],交易盤別=[{OrdLot}]".format(OrderNo=pkg.OrderNo, Market=pkg.Market, StockID=pkg.StockID, OrdLot=pkg.OrdLot))
        print("委託回報--委託書號=[{OrderNo}],買賣別=[{Side}],委託種類=[{OrdClass}],委託價格=[{Price}]".format(OrderNo=pkg.OrderNo, Side=pkg.Side, OrdClass=pkg.OrdClass, Price=pkg.Price))
        print("委託回報--委託書號=[{OrderNo}],改量前數量=[{BeforeQty}],改量後數量=[{AfterQty}],錯誤代碼=[{ErrCode}],錯誤訊息=[{ErrMsg}]".format(OrderNo=pkg.OrderNo, BeforeQty=pkg.BeforeQty, AfterQty=pkg.AfterQty, ErrCode=pkg.ErrCode, ErrMsg=pkg.ErrMsg))
    elif (pkg.DT==DT.SECU_DEAL_RPT): 
        #成交回報
        print("成交回報--委託書號=[{OrderNo}],委託型態=[{OrderFunc}],帳號=[{BrokerId}{Account}],回報時間=[{ReportTime}]".format(OrderNo=pkg.OrderNo, OrderFunc=pkg.OrderFunc, BrokerId=pkg.BrokerId, Account=pkg.Account,ReportTime=pkg.ReportTime))
        print("成交回報--委託書號=[{OrderNo}],市場別=[{Market}],商品代碼=[{StockID}],交易盤別=[{OrdLot}],買賣別=[{Side}]".format(OrderNo=pkg.OrderNo, Market=pkg.Market, StockID=pkg.StockID, OrdLot=pkg.OrdLot, Side=pkg.Side))
        print("成交回報--委託書號=[{OrderNo}],委託種類=[{OrdClass}],成交量=[{DealQty}]成交價格=[{Price}],市場成交序號=[{MarketNo}]".format(OrderNo=pkg.OrderNo, OrdClass=pkg.OrdClass, DealQty=pkg.DealQty, AfterQty=pkg.Price, MarketNo=pkg.MarketNo))
    elif (pkg.DT==DT.FINANCIAL_WSSETAMTTRIAL): 
        #當日交割金額試算查詢 
        print("當日交割金額試算回報 CODE=[{code}], CodeDesc=[{msg}], 筆數=[{rows1},{rows2}]".format(code=pkg.Code, msg=pkg.CodeDesc, rows1=pkg.Rows1, rows2=pkg.Rows2))
        if (pkg.Code == 0) :     
            pkgidx=0       
            for subpkg in pkg.Detail1:
                pkgidx = pkgidx+1
                print("當日交割金額試算回報-{idx}-類別=[{col1}],分公司=[{col2}],帳號=[{col3}],交易類別=[{col4}],買賣=[{col5}]".format(idx=pkgidx,col1=subpkg.DetailKind, col2=subpkg.BrokerId, col3=subpkg.Account, col4=subpkg.ordClass, col5=subpkg.BS))
                print("當日交割金額試算回報-{idx}-類別說明=[{col1}],商品代碼=[{col2}],櫃員序號=[{col3}],成交股數=[{col4}],成交價=[{col5}]".format(idx=pkgidx,col1=subpkg.Descript, col2=subpkg.Symbol, col3=subpkg.TERMSEQNO, col4=subpkg.QTY, col5=subpkg.PRICE))
                print("當日交割金額試算回報-{idx}-價金=[{col1}],手續費=[{col2}],交易稅=[{col3}],融資金額=[{col4}],融資自備款=[{col5}]".format(idx=pkgidx,col1=subpkg.AMT, col2=subpkg.FEE, col3=subpkg.TAX, col4=subpkg.CRDBAMT, col5=subpkg.CRSFAMT))
                print("當日交割金額試算回報-{idx}-融券保證金=[{col1}],融券擔保品=[{col2}],融資利息=[{col3}],證所稅/二代健保費=[{col4}],融券手續費=[{col5}]".format(idx=pkgidx,col1=subpkg.GTAMT, col2=subpkg.DNAMT, col3=subpkg.CRDBINT, col4=subpkg.INSUFEE, col5=subpkg.DBDLFEE))
                print("當日交割金額試算回報-{idx}-標借費=[{col1}],客戶應付金額=[{col2}],客戶應收付金額=[{col3}],原幣損益=[{col4}],下單來源=[{col5}]".format(idx=pkgidx,col1=subpkg.BNFEE, col2=subpkg.RECAMT, col3=subpkg.NETAMT, col4=subpkg.NETPL, col5=subpkg.SOURCE))
                print("當日交割金額試算回報-{idx}-市埸別=[{col1}],債息=[{col2}],現股當沖券差=[{col3}],交割幣別=[{col4}],約當台幣損益=[{col5}]".format(idx=pkgidx,col1=subpkg.MKTYPE, col2=subpkg.BONDINT, col3=subpkg.DIFFQTY, col4=subpkg.CURRENCY, col5=subpkg.NETPLTWD))
            
            #當日交割金額_當沖股票彙總
            pkgidx=0
            for subpkg in pkg.Detail2:
                pkgidx = pkgidx+1
                print("當日交割金額試算回報-{idx}-分公司=[{col1}],帳號=[{col2}],商品代碼=[{col3}],交易類別=[{col4}],商品名稱=[{col5}]".format(idx=pkgidx,col1=subpkg.BrokerId, col2=subpkg.Account, col3=subpkg.Symbol, col4=subpkg.ordClass, col5=subpkg.SymbolName))
                print("當日交割金額試算回報-{idx}-當沖張數=[{col1}],買進均價=[{col2}],買進價金=[{col3}],買進手續費=[{col4}],買進合計=[{col5}]".format(idx=pkgidx,col1=subpkg.QTY, col2=subpkg.BAVGPRICE, col3=subpkg.BAMT, col4=subpkg.BFEE, col5=subpkg.BTOTAL))
                print("當日交割金額試算回報-{idx}-賣進均價=[{col1}],賣出價金=[{col2}],賣出手續費=[{col3}],賣出交易稅=[{col4}],融券手續費=[{col5}]".format(idx=pkgidx,col1=subpkg.SAVGPRICE, col2=subpkg.SAMT, col3=subpkg.SFEE, col4=subpkg.STAX, col5=subpkg.SDLFEE))
                print("當日交割金額試算回報-{idx}-賣出合計=[{col1}],證所稅/二代健保=[{col2}],當沖損益=[{col3}],未沖損益=[{col4}],交易單位股數=[{col5}]".format(idx=pkgidx,col1=subpkg.STOTAL, col2=subpkg.INSUFEE, col3=subpkg.PNLX, col4=subpkg.PNLNX, col5=subpkg.QUNIT))
                print("當日交割金額試算回報-{idx}-交割幣別=[{col1}],幣別名稱=[{col2}],當沖約當台幣損益=[{col3}],非當沖約當台幣損益=[{col4}]".format(idx=pkgidx,col1=subpkg.CURRENCY, col2=subpkg.CURRNAME, col3=subpkg.NETPLTWDX, col4=subpkg.NETPLTWDNX))
            
    elif (pkg.DT==DT.FINANCIAL_WSSETAMTDETAIL): 
        #當日交割金額_沖銷明細(非當沖)查詢 
        print("當日交割金額_沖銷明細(非當沖)回報 CODE=[{code}], CodeDesc=[{msg}], 筆數=[{rows}]".format(code=pkg.Code, msg=pkg.CodeDesc, rows=pkg.Rows))
        if (pkg.Code == 0) :
            pkgidx=0
            for subpkg in pkg.Detail:
                pkgidx = pkgidx+1
                print("當日交割金額_沖銷明細(非當沖)回報-{idx}-分公司=[{col1}],帳號=[{col2}],類別說明=[{col3}],交易日期=[{col4}],商品代碼=[{col5}]".format(idx=pkgidx,col1=subpkg.BrokerId, col2=subpkg.Account, col3=subpkg.Descript, col4=subpkg.TradeDate, col5=subpkg.Symbol))
                print("當日交割金額_沖銷明細(非當沖)回報-{idx}-商品名稱=[{col1}],櫃員序號=[{col2}],成交股數=[{col3}],成交價=[{col4}],成交金額=[{col5}]".format(idx=pkgidx,col1=subpkg.SymbolName, col2=subpkg.TERMSEQNO, col3=subpkg.QTY, col4=subpkg.PRICE, col5=subpkg.AMT))
                print("當日交割金額_沖銷明細(非當沖)回報-{idx}-手續費=[{col1}],交易稅=[{col2}],融資金額=[{col3}],融資自備款=[{col4}],融券保證金=[{col5}]".format(idx=pkgidx,col1=subpkg.FEE, col2=subpkg.TAX, col3=subpkg.CRDBAMT, col4=subpkg.CRSFAMT, col5=subpkg.GTAMT))
                print("當日交割金額_沖銷明細(非當沖)回報-{idx}-融券擔保品=[{col1}],融資利息=[{col2}]".format(idx=pkgidx,col1=subpkg.DNAMT, col2=subpkg.CRDBINT))
    elif (pkg.DT==DT.FINANCIAL_WSSETTLEAMT): 
        #交割金額查詢(3日)查詢
        print("交割金額查詢(3日)回報 CODE=[{code}], CodeDesc=[{msg}], 筆數=[{rows}]".format(code=pkg.Code, msg=pkg.CodeDesc, rows=pkg.Rows))
        if (pkg.Code == 0) :   
            pkgidx=0         
            for subpkg in pkg.Detail:
                pkgidx = pkgidx+1
                print("交割金額查詢(3日)回報-{idx}-分公司=[{col1}],帳號=[{col2}],交割幣別=[{col3}],幣別名稱=[{col4}],成交日期(T-2)=[{col5}]".format(idx=pkgidx,col1=subpkg.BrokerId, col2=subpkg.Account, col3=subpkg.CURRENCY, col4=subpkg.CURRNAME, col5=subpkg.DealDate1))
                print("交割金額查詢(3日)回報-{idx}-交割日期0=[{col1}],結帳註記0=[{col2}],今日客戶應交割=[{col3}],成交日期 (T-1)=[{col4}],交割日期1=[{col5}]".format(idx=pkgidx,col1=subpkg.CDate1, col2=subpkg.SettleMark1, col3=subpkg.CSRPAMT1, col4=subpkg.DealDate2, col5=subpkg.CDate2))
                print("交割金額查詢(3日)回報-{idx}-結帳註記1=[{col1}],次日客戶應交割=[{col2}],成交日期 (T)=[{col3}],交割日期2 (T-1)=[{col4}],結帳註記2=[{col5}]".format(idx=pkgidx,col1=subpkg.SettleMark2, col2=subpkg.CSRPAMT2, col3=subpkg.DealDate3, col4=subpkg.CDate3, col5=subpkg.SettleMark3))
                print("交割金額查詢(3日)回報-{idx}-次二日客戶應交割=[{col1}]".format(idx=pkgidx,col1=subpkg.CSRPAMT3))

    elif (pkg.DT==DT.FINANCIAL_WSINVENTORY):
        #庫存損益及即時維持率試算查詢
        print("庫存損益及即時維持率試算回報, 帳號:[{brk}-{act}] CODE=[{code}], CodeDesc=[{msg}], 筆數=[{rows}]".format(brk=pkg.BrokerID, act=pkg.Account, code=pkg.Code, msg=pkg.CodeDesc, rows=pkg.Rows))
        if (pkg.Code == 0) :
            pkgidx=0
            for subpkg in pkg.Detail:
                pkgidx = pkgidx+1
                print("庫存損益及即時維持率試算回報-{idx}-類別=[{col1}],交易日期=[{col2}],到期日期=[{col3}],交易序號=[{col4}],商品代碼=[{col5}]".format(idx=pkgidx,col1=subpkg.DetailKind, col2=subpkg.TradeDate, col3=subpkg.ExpiredDate, col4=subpkg.TERMSEQNO, col5=subpkg.Symbol))
                print("庫存損益及即時維持率試算回報-{idx}-交易類別=[{col1}],原始買進股數=[{col2}],原留股數=[{col3}],股數=[{col4}],成交價=[{col5}]".format(idx=pkgidx,col1=subpkg.ordClass, col2=subpkg.QTY0, col3=subpkg.QTY, col4=subpkg.RQTY, col5=subpkg.ORIPRICE))
                print("庫存損益及即時維持率試算回報-{idx}-成本價=[{col1}],帳面收入=[{col2}],出清試算=[{col3}],損益=[{col4}],自訂成本損益率=[{col5}]".format(idx=pkgidx,col1=subpkg.PRICE, col2=subpkg.ASSETREAL, col3=subpkg.SALENET, col4=subpkg.NETPL, col5=subpkg.PNLRATE))
                print("庫存損益及即時維持率試算回報-{idx}-現價=[{col1}],庫存市值=[{col2}],個筆維持率=[{col3}],個筆維持分子=[{col4}],筆維持率分母=[{col5}]".format(idx=pkgidx,col1=subpkg.RLPRICE, col2=subpkg.ASSET, col3=subpkg.SUTRATE, col4=subpkg.SUTRATEA, col5=subpkg.SUTRATEB))
                print("庫存損益及即時維持率試算回報-{idx}-原始融資金額=[{col1}],未償還融資金額=[{col2}],融資自備款(原始)=[{col3}],未償還融資自備款=[{col4}],利息=[{col5}]".format(idx=pkgidx,col1=subpkg.CRDBAMT0, col2=subpkg.CRDBAMT, col3=subpkg.CRSFAMT0, col4=subpkg.CRSFAMT, col5=subpkg.CRDBINT))
                print("庫存損益及即時維持率試算回報-{idx}-證所稅/二代健保=[{col1}],標借利息=[{col2}],保證品價值=[{col3}],追繳碼=[{col4}],假除權價=[{col5}]".format(idx=pkgidx,col1=subpkg.INSUFEE, col2=subpkg.BFINT, col3=subpkg.RTAMT, col4=subpkg.ADDAMTCODE, col5=subpkg.ADJPRICE))
                print("庫存損益及即時維持率試算回報-{idx}-試算價=[{col1}],自訂成本=[{col2}],自訂損益=[{col3}],自訂成本註記=[{col4}],投資成本=[{col5}]".format(idx=pkgidx,col1=subpkg.ASSETADJ, col2=subpkg.SFPRICE, col3=subpkg.SFPNL, col4=subpkg.SFMARK, col5=subpkg.COST))
                print("庫存損益及即時維持率試算回報-{idx}-手續費率=[{col1}],融券手續費率=[{col2}],交易稅率=[{col3}],可否自訂成本=[{col4}],交易單位股數=[{col5}]".format(idx=pkgidx,col1=subpkg.FEERATE, col2=subpkg.DLFEERATE, col3=subpkg.TAXRATE, col4=subpkg.SWSETPRICE, col5=subpkg.QUNIT))
                print("庫存損益及即時維持率試算回報-{idx}-價格比例=[{col1}],幣別=[{col2}],幣別名稱=[{col3}],約當台幣損益=[{col4}],(買進)滙率=[{col5}]".format(idx=pkgidx,col1=subpkg.PRICERATE, col2=subpkg.CURRENCY, col3=subpkg.CURRNAME, col4=subpkg.NETPLTWD, col5=subpkg.EXRATE_B))
            
    elif (pkg.DT==DT.FINANCIAL_WSINVENTORYSUM):
        #證券庫存彙總查詢, 庫存資料量大, 分多筆送回, 故須自行判斷是否傳送完畢(NowCount = TotalCount), 須注意, 若同一時間查詢多次時, 會造成封包穿插送回, 資料會異常
        print("證券庫存彙總查詢 CODE=[{code}], 帳號:[{brk}-{act}], CodeDesc=[{msg}], 筆數=[{rows}/{total}]".format(code=pkg.Code, brk=pkg.BrokerID, act=pkg.Account, msg=pkg.CodeDesc, rows=pkg.NowCount, total=pkg.TotalCount))
        if (pkg.Code == 0) :
            for subpkg in pkg.Detail:                
                print("證券庫存彙總查詢回報-{idx}-商品代碼=[{col1}],商品名稱=[{col2}],[*現貨*]昨日餘額=[{col3}],當日新增-委託=[{col4}],當日新增-成交=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.Symbol, col2=subpkg.SymbolName, col3=subpkg.RQTY0, col4=subpkg.IORDQTY, col5=subpkg.IMATQTY0))
                print("證券庫存彙總查詢回報-{idx}-當日出清-委託=[{col1}],當日出清-成交=[{col2}],現股-可出清餘額=[{col3}],現股-可下單餘額=[{col4}],今日餘額股數=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.OORDQTY0, col2=subpkg.OMATQTY0, col3=subpkg.SALEQTY0, col4=subpkg.AORDQTY0, col5=subpkg.NETQTY0))
                print("證券庫存彙總查詢回報-{idx}-券差數量=[{col1}],出借數量=[{col2}],可賣出借數量=[{col3}],滙撥=[{col4}],扣押=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.IRQTY0, col2=subpkg.ORQTY0, col3=subpkg.SRQTY0, col4=subpkg.ICTLQTY0, col5=subpkg.OCTLQTY0))
                print("證券庫存彙總查詢回報-{idx}-[*零股*]昨日餘額=[{col1}],當日新增-委託=[{col2}],當日新增-成交=[{col3}],當日出清-委託=[{col4}],當日出清-成交=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.RQTY9, col2=subpkg.IORDQTY9, col3=subpkg.IMATQTY9, col4=subpkg.OORDQTY9, col5=subpkg.OMATQTY9))
                print("證券庫存彙總查詢回報-{idx}-可出清餘額=[{col1}],可下單餘額=[{col2}],今日餘額股數=[{col3}],[*融資*]昨日餘額=[{col4}],當日新增-委託=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.SALEQTY9, col2=subpkg.AORDQTY9, col3=subpkg.NETQTY9, col4=subpkg.RQTY3, col5=subpkg.IORDQTY3))
                print("證券庫存彙總查詢回報-{idx}-當日新增-成交=[{col1}],當日出清-委託=[{col2}],當日出清-成交=[{col3}],可出清餘額=[{col4}],可下單餘額=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.IMATQTY3, col2=subpkg.OORDQTY3, col3=subpkg.OMATQTY3, col4=subpkg.SALEQTY3, col5=subpkg.AORDQTY3))
                print("證券庫存彙總查詢回報-{idx}-今日餘額股數=[{col1}],處份=[{col2}],解處份=[{col3}],[*融券*]昨日餘額=[{col4}],當日新增-委託=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.NETQTY3, col2=subpkg.OCTLQTY3, col3=subpkg.ICTLQTY3, col4=subpkg.RQTY4, col5=subpkg.IORDQTY4))
                print("證券庫存彙總查詢回報-{idx}-當日新增-成交=[{col1}],當日出清-委託=[{col2}],當日出清-成交=[{col3}],可出清餘額=[{col4}],可下單餘額=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.IMATQTY4, col2=subpkg.OORDQTY4, col3=subpkg.OMATQTY4, col4=subpkg.SALEQTY4, col5=subpkg.AORDQTY4))
                print("證券庫存彙總查詢回報-{idx}-今日餘額股數=[{col1}],處份=[{col2}],解處份=[{col3}],資券當沖數量=[{col4}],即時價=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.NETQTY4, col2=subpkg.OCTLQTY4, col3=subpkg.ICTLQTY4, col4=subpkg.DTRQTY, col5=subpkg.RLPRICE))
                print("證券庫存彙總查詢回報-{idx}-庫存市值=[{col1}],帳面收入=[{col2}],未實現損益=[{col3}],市場別=[{col4}],成交均價(現)=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.ASSET, col2=subpkg.ASSETREAL, col3=subpkg.NETPL, col4=subpkg.MKTYPE, col5=subpkg.OAVGPRICE0))
                print("證券庫存彙總查詢回報-{idx}-成交均價(資)=[{col1}],成交均價(券)=[{col2}],成本均價(現)=[{col3}],成本均價(資)=[{col4}],成本均價(券)=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.OAVGPRICE3, col2=subpkg.OAVGPRICE4, col3=subpkg.AVGPRICE0, col4=subpkg.AVGPRICE3, col5=subpkg.AVGPRICE4))
                print("證券庫存彙總查詢回報-{idx}-權證到期日=[{col1}],交易單位股數=[{col2}],現股當沖數量=[{col3}],是否可現股當沖=[{col4}],價格比率=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.EXPDATE, col2=subpkg.QUNIT, col3=subpkg.DTQTY0, col4=subpkg.DTCHECK0, col5=subpkg.PRICE_RATE))
                print("證券庫存彙總查詢回報-{idx}-幣別=[{col1}],幣別名稱=[{col2}],約當台幣損益=[{col3}],(買進)滙率=[{col4}],券差出借=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.CURRENCY, col2=subpkg.CURRNAME, col3=subpkg.NETPLTWD, col4=subpkg.EXRATEB, col5=subpkg.B_RQTY))
                print("證券庫存彙總查詢回報-{idx}-客戶出借1日還券=[{col1}],客戶出借3日還券=[{col2}],客戶借券=[{col3}],昨日餘額=[{col4}],當日借券賣出-委託=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.LSML04001, col2=subpkg.LSML04003, col3=subpkg.LSSL0400, col4=subpkg.R_QTY5, col5=subpkg.O_ORDQTY5))
                print("證券庫存彙總查詢回報-{idx}-當日借券賣出-成交=[{col1}],借入可下單數量=[{col2}],借入可出清數量=[{col3}],今日餘額股數=[{col4}]".format(idx=pkg.NowCount,col1=subpkg.O_MATQTY5, col2=subpkg.SALEQTY5, col3=subpkg.AORDQTY5, col4=subpkg.NETQTY5))

            if (pkg.NowCount == pkg.TotalCount): print("--------------------庫存損益及即時維持率試算回報--最後一筆--------------------")
    elif (pkg.DT==DT.FINANCIAL_WSBALANCESTATEMENT):
        #證券對帳單查詢
        print("證券對帳單回報 CODE=[{code}], 帳號:[{brk}-{act}], CodeDesc=[{msg}], CodeDesc=[{msg}], 筆數=[{rows}/{total}]".format(code=pkg.Code, brk=pkg.BrokerID, act=pkg.Account, msg=pkg.CodeDesc, rows=pkg.NowCount, total=pkg.TotalCount))
        if (pkg.Code == 0) :                     
            for subpkg in pkg.Detail:
                print("證券對帳單回報-{idx}-序號=[{col1}],交易日期=[{col2}],委託別=[{col3}]".format(idx=pkg.NowCount,col1=subpkg.Seq, col2=subpkg.TradeDate, col3=subpkg.ordClass))
                print("證券對帳單回報-{idx}-買賣別=[{col1}],當沖=[{col2}],類別說明=[{col3}],商品代碼=[{col4}],商品名稱=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.BS, col2=subpkg.DayTrade, col3=subpkg.Descript, col4=subpkg.Symbol, col5=subpkg.SymbolName))
                print("證券對帳單回報-{idx}-櫃員序號=[{col1}],成交股數=[{col2}],成交價=[{col3}],成交金額=[{col4}],手續費=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.TERMSEQNO, col2=subpkg.QTY, col3=subpkg.PRICE, col4=subpkg.AMT, col5=subpkg.FEE))
                print("證券對帳單回報-{idx}-交易稅=[{col1}],融資/沖銷金額=[{col2}],融資/沖銷自備款=[{col3}],融券/沖銷保證金=[{col4}],融券/沖銷擔保品=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.TAX, col2=subpkg.CRDBAMT, col3=subpkg.CRSFAMT, col4=subpkg.GTAMT, col5=subpkg.DNAMT))
                print("證券對帳單回報-{idx}-融資/保證金利息=[{col1}],債息=[{col2}],證所稅/二代健保補充=[{col3}],融券手續費/借券費(標借費)=[{col4}]客戶應收=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.CRDBINT, col2=subpkg.BONDINT, col3=subpkg.INSUFEE, col4=subpkg.DBDLFEE, col5=subpkg.CSRECAMT))
                print("證券對帳單回報-{idx}-客戶應付=[{col1}],客戶應收金額=[{col2}],損益=[{col3}],下單來源=[{col4}],市埸別=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.CSPAYAMT, col2=subpkg.NETAMT, col3=subpkg.NETPL, col4=subpkg.SOURCE, col5=subpkg.MKTYPE))
                print("證券對帳單回報-{idx}-當沖損益=[{col1}],幣別=[{col2}],幣別名稱=[{col3}]".format(idx=pkg.NowCount,col1=subpkg.PNLDTRADE, col2=subpkg.CURRENCY, col3=subpkg.CURRNAME))
            
            if (pkg.NowCount == pkg.TotalCount): print("--------------------證券對帳單回報--最後一筆--------------------")
    elif (pkg.DT==DT.FINANCIAL_WSREALIZEPL):
        #證券已實現損益
        print("證券已實現損益 CODE=[{code}], 帳號:[{brk}-{act}], CodeDesc=[{msg}], 筆數=[{rows}/{total}]".format(code=pkg.Code, brk=pkg.BrokerID, act=pkg.Account, msg=pkg.CodeDesc, rows=pkg.NowCount, total=pkg.TotalCount))
        if (pkg.Code == 0) :
            for subpkg in pkg.Detail:                
                print("證券已實現損益回報-{idx}-序號=[{col1}],商品代碼=[{col2}],商品名稱=[{col3}]".format(idx=pkg.NowCount,col1=subpkg.Seq, col2=subpkg.Symbol, col3=subpkg.SymbolName))
                print("證券已實現損益回報-{idx}-交易日期=[{col1}],櫃員序號=[{col2}],委託別=[{col3}],買賣別=[{col4}],當沖=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.TradeDate, col2=subpkg.TERMSEQNO, col3=subpkg.ordClass, col4=subpkg.BS, col5=subpkg.DayTrade))
                print("證券已實現損益回報-{idx}-類別說明=[{col1}],成交股數=[{col2}],成交價=[{col3}],成交價(均價)=[{col4}],價金=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.Descript, col2=subpkg.QTY, col3=subpkg.ORIPRICE, col4=subpkg.PRICE, col5=subpkg.AMT))
                print("證券已實現損益回報-{idx}-手續費=[{col1}],交易稅=[{col2}],融資/沖銷金額=[{col3}],融資/沖銷自備款=[{col4}],融券/沖銷保證金=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.FEE, col2=subpkg.TAX, col3=subpkg.CRDBAMT, col4=subpkg.CRSFAMT, col5=subpkg.GTAMT))
                print("證券已實現損益回報-{idx}-融券/沖銷擔保品=[{col1}],融資/保證金利息=[{col2}],債息=[{col3}],證所稅/二代健保補充=[{col4}],融券手續費/借券費(標借費)=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.DNAMT, col2=subpkg.CRDBINT, col3=subpkg.BONDINT, col4=subpkg.INSUFEE, col5=subpkg.DBDLFEE))
                print("證券已實現損益回報-{idx}-客戶應收=[{col1}],損益=[{col2}],損益率=[{col3}],投資成本=[{col4}],自設投資成本=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.NETAMT, col2=subpkg.NETPL, col3=subpkg.PNLRATE, col4=subpkg.COST, col5=subpkg.SFCOST))
                print("證券已實現損益回報-{idx}-自設損益=[{col1}],自設損益率=[{col2}],自設成交註記=[{col3}],價格比例=[{col4}],幣別=[{col5}]".format(idx=pkg.NowCount,col1=subpkg.SFPNL, col2=subpkg.SFPNLRATE, col3=subpkg.SFMARK, col4=subpkg.PRICERATE, col5=subpkg.CURRENCY))

            if (pkg.NowCount == pkg.TotalCount): print("--------------------證券已實現損益回報--最後一筆--------------------")            
    elif (pkg.DT==DT.SECU_CREDITINFO):
        print("資券餘額查詢")
        #資券餘額查詢
        print("資券餘額查詢-CODE=[{code}],CodeDesc=[{msg}],證券代號=[{stock}],證券名稱=[{name}]".format(code=pkg.ErrCode, msg=pkg.ErrMsg, stock=pkg.StockNO, name=pkg.StockName))
        print("資券餘額查詢--來源別=[{col1}],現股交易狀態=[{col2}],融資狀況=[{col3}],融券狀況=[{col4}],市場別=[{col5}]".format(col1=pkg.Source, col2=pkg.DealStatus, col3=pkg.MarginStatus, col4=pkg.ShortStatus, col5=pkg.Market))
        print("資券餘額查詢--證券分類=[{col1}],上市分類=[{col2}],停資日起=[{col3}],停資日迄=[{col4}],停券日起=[{col5}]".format(col1=pkg.StockType, col2=pkg.TransType, col3=pkg.MarginDateB, col4=pkg.MarginDateB, col5=pkg.ShortDateB))
        print("資券餘額查詢--停券日迄=[{col1}],停資券註記=[{col2}],融資配額張數=[{col3}],融卷配額張數=[{col4}],高融成數=[{col5}]".format(col1=pkg.ShortDateE, col2=pkg.StopMark, col3=pkg.MarignQty, col4=pkg.ShortQty, col5=pkg.HPercent))
        print("資券餘額查詢--低融成數=[{col1}],保證金成數=[{col2}],平盤下可否放空=[{col3}],可否融券當沖=[{col4}],融券最後回補日=[{col5}]".format(col1=pkg.LPercent, col2=pkg.DepositRate, col3=pkg.MarkM, col4=pkg.MarkT, col5=pkg.ShortLastDate))
        print("資券餘額查詢--融資成數=[{col1}],融券成數=[{col2}],券商警示=[{col3}],現股當沖碼=[{col4}],市場控管=[{col5}]".format(col1=pkg.MarginRate, col2=pkg.ShortRate, col3=pkg.BrokerWarn, col4=pkg.DTCode, col5=pkg.MarketControl))
        print("資券餘額查詢--預收款券=[{col1}],交易單位股數=[{col2}],價金乘數=[{col3}],幣別=[{col4}],幣別名稱=[{col5}]".format(col1=pkg.PGCL, col2=pkg.TradeUnit, col3=pkg.TradeUT2, col4=pkg.Currency, col5=pkg.CurrName))
    
    print("***請輸入指令:")
    
#QuoteCom initialize 
def initialize():  
    global tradeCom    
    global ridDict

    sid='API'
    print("TradeCom API initialize........")   
    tradeCom = TaiFexCom("", 8000, sid)
    ridDict=dict()
    # register event handler
    #狀態通知事件KGI TradeCom API message event
    tradeCom.OnRcvMessage += onTradeRcvMessage
    #資料接收事件 KGI TradeCom API status event
    tradeCom.OnGetStatus += onTradeGetStatus
    #回補狀態通知 KGI TradeCom API recover status event
    tradeCom.OnRecoverStatus += OnRecoverStatus
    print("END TradeCom API initialize........")   

    return

def SendOrder(brokerid, account, stockid, otype, oLot, oclass, pflag, bs, qty, prz, agend, orderno, tif):   
    #委託別: O.下單 C.刪單 P.改量 Q.改價 
    if (otype=='O'):
        ordType=Security_OrdType.OT_NEW
    elif (otype=='C'):
        ordType=Security_OrdType.OT_CANCEL
    elif (otype=='P'):
        ordType=Security_OrdType.OT_MODIFY_PRICE
    elif (otype=='Q'):
        ordType=Security_OrdType.OT_MODIFY_QTY
    else:
        print("送單失敗,委託別["+otype+"]輸入錯誤!")
        return False

    #交易盤別: 0.整股 1.零股 2.定價 3.鉅額 4.盤中零股
    if (oLot=='0'):
        ordLot=Security_Lot.Even_Lot
    elif (oLot=='1'):
        ordLot=Security_Lot.Odd_Lot
    elif (oLot=='2'):
        ordLot=Security_Lot.Fixed_Price
    elif (oLot=='3'):
        ordLot=Security_Lot.Block_Trade
    elif (oLot=='4'):
        ordLot=Security_Lot.Odd_InTraday
    else:
        print("送單失敗,交易盤別["+oLot+"]輸入錯誤!")
        return False

    #委託種類: 0.現股 3.自資 4.自券 5.借券賣出 6.借券賣出(盤下限制豁免) 7.當沖融資 8.當沖融券 9.現先賣
    if (oclass=='0'):
        ordClass=Security_Class.SC_Ordinary
    elif (oclass=='3'):
        ordClass=Security_Class.SC_SelfMargin
    elif (oclass=='4'):
        ordClass=Security_Class.SC_SelfShort 
    elif (oclass=='5'):
        ordClass=Security_Class.SC_ShortLimit
    elif (oclass=='6'):
        ordClass=Security_Class.SC_ShortUnLimit
    elif (oclass=='7'):
        ordClass=Security_Class.SC_DayMargin
    elif (oclass=='8'):
        ordClass=Security_Class.SC_DayShort
    elif (oclass=='9'):
        ordClass=Security_Class.SC_DayTrade
    else:
        print("送單失敗,交易盤別["+oclass+"]輸入錯誤!")
        return False

    #價格旗標: 0.限價 1.跌停 2.平盤 3.漲停 4.巿價
    if (pflag=='0'):
        priceFlag=Security_PriceFlag.SP_FixedPrice
    elif (pflag=='1'):
        priceFlag=Security_PriceFlag.SP_FallStopPrice
    elif (pflag=='2'):
        priceFlag=Security_PriceFlag.SP_UnchangePrice 
    elif (pflag=='3'):
        priceFlag=Security_PriceFlag.SP_RiseStopPrice
    elif (pflag=='4'):
        priceFlag=Security_PriceFlag.SP_MarketPrice
    else:
        print("送單失敗,價格旗標["+pflag+"]輸入錯誤!")
        return False

    #買賣別 B:買 S:賣
    if (bs == 'B'):
        side = SIDE_FLAG.SF_BUY
    elif (bs == 'S'):
        side = SIDE_FLAG.SF_SELL
    else:
        print("送單失敗,買賣別["+bs+"]輸入錯誤!")
        return False

    #委託條件 : R:ROC I:IOC F:FOK
    if (tif=='R'):
        timeinforce=TIME_IN_FORCE.TIF_ROD
    elif (tif=='F'):
        timeinforce=TIME_IN_FORCE.TIF_FOK
    elif (tif=='I'):
        timeinforce=TIME_IN_FORCE.TIF_IOC 
    else:
        print("送單失敗,委託條件["+tif+"]輸入錯誤!")
        return False

    ordQty=UInt16(qty)    
    ordPrz=CSDecimal(float(prz))

    ##取得送單序號,以便回報時對應
    rid=tradeCom.GetRequestId()   
    requestId = Int64(rid)
    print("送單 RequestId=[{rid}]".format(rid=requestId))
    
    rtn = tradeCom.SecurityOrder(requestId, ordType, ordLot, ordClass, brokerid, account, stockid, side, ordQty, ordPrz, priceFlag, ' ', agend, orderno, timeinforce );
    if (rtn != 0):
        print("SecurityOrder Error :"+str(rtn));
        print(tradeCom.GetOrderErrMsg(rtn))

    return True