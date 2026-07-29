import clr
import sys
import builtins

assembly_path = r"C:\Users\User\Desktop\AlgoTrade\QuoteComExamplePy"
sys.path.append(assembly_path)

clr.AddReference("Package")      #必要引用dll
clr.AddReference("PushClient")   #必要引用dll
clr.AddReference("QuoteCom")     #必要引用dll
from Package import PackageBase  #from namespace import class
from Package import P001503         #from namespace import class
from Intelligence import PushClient #from namespace import class
from Intelligence import QuoteCom   #from namespace import class
from Intelligence import COM_STATUS #from namespace import class
from Intelligence import DT         #from namespace import class
from Intelligence import IdxKind    #from namespace import class

#接收KGI QuoteCom API status event
def onQuoteGetStatus(sender, status, msg):
    smsg = bytes(msg).decode('UTF-8','strict')
     
    if (status==COM_STATUS.CONNECT_READY):        
        print("STATUS:CONNECT_READY:["+smsg+"]")
    elif (status==COM_STATUS.CONNECT_FAIL):
        print("STATUS:CONNECT_FAIL:["+smsg+"]")
    elif (status==COM_STATUS.SUBSCRIBE):
        print("STATUS:SUBSCRIBE:["+smsg[:len(smsg)-1]+"]")
    elif (status==COM_STATUS.DISCONNECTED):
        print("STATUS:DISCONNECTED:["+smsg+"]")
    elif (status==COM_STATUS.LOGIN_READY):
        print("STATUS:LOGIN_READY:["+smsg+"]")		
    elif (status==COM_STATUS.LOGIN_FAIL):
        print("STATUS:LOGIN_FAIL:["+smsg+"]")				
    elif (status==COM_STATUS.LOGIN_UNKNOW):
        print("STATUS:LOGIN_UNKNOW:["+smsg+"]")						
    elif (status==COM_STATUS.UNSUBSCRIBE):
        print("STATUS:UNSUBSCRIBE:["+smsg[:len(smsg)-1]+"]")								
    elif (status==COM_STATUS.ACK_REQUESTID):
        print("STATUS:ACK_REQUESTID:["+smsg+"]")	
        print("STATUS:ACK_REQUESTID:RequestId=["+int.from_bytes(msg[0:8], byteorder='big')+"]status=["+msg[8]+"]\n")									
    elif (status==COM_STATUS.RECOVER_DATA):
        print("STATUS:RECOVER_DATA:["+smsg+"]")
        if (msg[0] == 0):
            print("STATUS:RECOVER_DATA Start Topic:["+msg[1:]+"]")
        elif (msg[0] == 1):
            print("STATUS:RECOVER_DATA End Topic:["+msg[1:]+"]")	
    else:
        print("STATUS:UNKNOW={st}, msg=[{ms}]".format(st=status, ms=smsg)) 
        
    print('***請輸入指令:')
    
    return

#接收KGI QuoteCom API message event
def onQuoteRcvMessage(sender, pkg):   
    if (pkg.DT==DT.LOGIN): 
        #登入回覆  
        if (int(quoteCom.QuoteStock)==True): 
            print("可註冊證券報價")
            if (pkg.Code==0):
                print("可註冊檔數：{Qnum}\n".format(Qnum=pkg.Qnum))
        else:
            print("無證券報價API權限")
    elif (pkg.DT==DT.NOTICE): #公告
        print("公告:" , pkg.ToLog())
    elif (pkg.DT==DT.QUOTE_STOCK_MATCH1 or pkg.DT==DT.QUOTE_STOCK_MATCH2): 
        #上市/上櫃成交揭示
        if (pkg.DT==int(DT.QUOTE_STOCK_MATCH1)) : 
            market='上巿'
        else:
            market='上櫃'        
        if (pkg.Status==0) :
            txstatus='<試撮>'
        else:
            txstatus=''
        print("{mkt} {stock} 成交揭示{status}-->資料時間:[{time}],成交價:[{price}],成交量:[{qty}],總量:[{tqty}]".format(mkt=market,stock=pkg.StockNo,status=txstatus,time=pkg.Match_Time, price=pkg.Match_Price,qty=pkg.Match_Qty, tqty=pkg.Total_Qty));
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_STOCK_DEPTH1 or pkg.DT==DT.QUOTE_STOCK_DEPTH2): 
        #上市/上櫃五檔揭示        
        if (pkg.DT==int(DT.QUOTE_STOCK_MATCH1)) : 
            market='上巿'    
        else:
            market='上櫃'    
        if (pkg.Status==0) :
            txstatus='<試撮>' 
        else:
            txstatus=''
        print("{mkt}[{stock}] 五檔揭示{status}-->資料時間:[{time}]".format(mkt=market,stock=pkg.StockNo,status=txstatus,time=pkg.Match_Time)) 
        idx=0          
        while (idx<5):
            print("第[{level}]檔 委買[價:{bidprz} 量:{bidqty}]  委賣[價:{askprz} 量:{askqty}]".format(level=idx+1, bidprz=pkg.BUY_DEPTH[idx].PRICE, bidqty=pkg.BUY_DEPTH[idx].QUANTITY, askprz=pkg.SELL_DEPTH[idx].PRICE, askqty=pkg.SELL_DEPTH[idx].QUANTITY))
            idx = idx + 1            
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_LAST_PRICE_STOCK):
        #最後價格        
        print("{stock} 最後價格-->成交價:[{price}],成交量:[{qty}],總量:[{tqty}],開盤:[{firstqty}],當日最高:[{highprz}],當日最低:[{lowprz}]".format(stock=pkg.StockNo,price=pkg.LastMatchPrice,qty=pkg.LastMatchQty, tqty=pkg.TotalMatchQty, firstqty=pkg.FirstMatchPrice, highprz=pkg.DayHighPrice, lowprz=pkg.DayLowPrice));
        idx=0
        while (idx<5):            
            print("第[{level}]檔--委買[價:{bidprz} 量:{bidqty}]  委賣[價:{askprz} 量:{askqty}]".format(level=idx+1, bidprz=pkg.BUY_DEPTH[idx].PRICE, bidqty=pkg.BUY_DEPTH[idx].QUANTITY, askprz=pkg.SELL_DEPTH[idx].PRICE, askqty=pkg.SELL_DEPTH[idx].QUANTITY))
            idx = idx + 1        
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_ODD_MATCH1 or pkg.DT==DT.QUOTE_ODD_MATCH2): 
        #盤中零股成交揭示
        if (pkg.DT==int(DT.QUOTE_ODD_MATCH1)) : 
            market='上巿'
        else:
            market='上櫃'        
        if (pkg.Status==0) :
            txstatus='<試撮>'
        else:
            txstatus=''
        print("{mkt} {stock} 成交揭示(盤中零股){status}-->資料時間:[{time}],成交價:[{price}],成交量:[{qty}],總量:[{tqty}]".format(mkt=market,stock=pkg.StockNo,status=txstatus,time=pkg.Match_Time, price=pkg.Match_Price,qty=pkg.Match_Qty, tqty=pkg.Total_Qty));
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_ODD_DEPTH1 or pkg.DT==DT.QUOTE_ODD_DEPTH2): 
        #盤中零股五檔揭示
        if (pkg.DT==int(DT.QUOTE_ODD_DEPTH1)) : 
            market='上巿'    
        else:
            market='上櫃'    
        if (pkg.Status==0) :
            txstatus='<試撮>' 
        else:
            txstatus='' 
        print("{mkt}{stock} 五檔揭示(盤中零股){status}-->資料時間:[{time}]".format(mkt=market,stock=pkg.StockNo,status=txstatus,time=pkg.Match_Time));    
        idx=0                  
        while (idx<5):
            print("第[{level}]檔 委買[價:{bidprz} 量:{bidqty}]  委賣[價:{askprz} 量:{askqty}]".format(level=idx+1, bidprz=pkg.BUY_DEPTH[idx].PRICE, bidqty=pkg.BUY_DEPTH[idx].QUANTITY, askprz=pkg.SELL_DEPTH[idx].PRICE, askqty=pkg.SELL_DEPTH[idx].QUANTITY))
            idx = idx + 1            
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_LAST_PRICE_ODD):
        #盤中零股最後價格        
        print("{stock} 最後價格(盤中零股)-->成交價:[{price}],成交量:[{qty}],總量:[{tqty}],開盤:[{firstqty}],當日最高:[{highprz}],當日最低:[{lowprz}]".format(stock=pkg.StockNo,price=pkg.LastMatchPrice,qty=pkg.LastMatchQty, tqty=pkg.TotalMatchQty, firstqty=pkg.FirstMatchPrice, highprz=pkg.DayHighPrice, lowprz=pkg.DayLowPrice));
        idx=0
        while (idx<5):            
            print("第[{level}]檔--委買[價:{bidprz} 量:{bidqty}]  委賣[價:{askprz} 量:{askqty}]".format(level=idx+1, bidprz=pkg.BUY_DEPTH[idx].PRICE, bidqty=pkg.BUY_DEPTH[idx].QUANTITY, askprz=pkg.SELL_DEPTH[idx].PRICE, askqty=pkg.SELL_DEPTH[idx].QUANTITY))
            idx = idx + 1        
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_STOCK_NEWINDEX1 or pkg.DT==DT.QUOTE_STOCK_NEWINDEX2):        
        if (pkg.DT==int(DT.QUOTE_STOCK_NEWINDEX1)) : 
            market='上巿'    
        else:
            market='上櫃'    
        print("[{mkt}指數]代號:[{indexId}] 時間：{mtime}, 指數:{last}".format(mkt=market,indexId=pkg.IndexNo, mtime=pkg.IndexTime, last=pkg.LatestIndex/100));        
        print("--------------------------------------------------------------------------------------------------")
    elif (pkg.DT==DT.QUOTE_LAST_NEWINDEX1 or pkg.DT==DT.QUOTE_LAST_NEWINDEX2):
        #最新指數查詢        
        if (pkg.DT==int(DT.QUOTE_LAST_NEWINDEX1)) : 
            market='上巿'    
        else:
            market='上櫃'            
        
        print("[{mkt}指數][{indexId}] 最新指數:{last},昨日收盤指數:{ref},開盤指數:{open},最高指數={high},最低指數={low}".
        format(mkt=market, indexId=pkg.IndexID, last=pkg.LastIndex/100, ref=pkg.RefIndex/100,open=pkg.OpenIndex/100,high=pkg.DayHighIndex/100,low=pkg.DayLowIndex/100))
        print("--------------------------------------------------------------------------------------------------")
    return

#QuoteCom initialize 
def initialize():  
    global quoteCom    
    token='b6eb'
    sid='API'
    print("QuoteCom API initialize........")   
    quoteCom = QuoteCom("", 443, sid, token)
    # register event handler
    #狀態通知事件KGI QuoteCom API message event
    quoteCom.OnRcvMessage += onQuoteRcvMessage
    #資料接收事件KGI QuoteCom API status event
    quoteCom.OnGetStatus += onQuoteGetStatus
    return
