from unicodedata import decimal
import clr
import sys
import builtins
import quotecomPy
from Intelligence import IdxKind    #from namespace import class

"""
指令                    功能            參數            說明及範例
-----------------------------------------------------------------------------------------
LOGIN                   登入             ID,PW           Ex: LOGIN,A123456789,0000 
LOGOUT                  登出
EXIT                    關閉程式
SUBSCRIBE               訂閱報價         StockID        #多組股票以|符號隔開, 單一股票 EX: SUBSCRIBE,2883  多組股票 EX: SUBSCRIBE,2883|2330|0050
UNSUBSCRIBE             解除訂閱報價     StockID        單一股票 EX: UNSUBSCRIBE,2883  多組股票 EX: UNSUBSCRIBE,2883|2330|0050
DOWNLOAD                下載上市檔
QUERYSTOCK              查詢商品基本資料                 要做完下載商品檔才查得到資料
LASTPRICE               查詢最後價格
SUBINDEX                訂閱新編指數報價 
UNSUBINDEX              解除訂閱新編指數報價
LASTINDEX               查詢最後指數     IndexID
"""

quotecomPy.initialize()

#command mode, 格式為: 指令,參數1,參數2,參數3........................
inputstr = input('請輸入指令:')
args = inputstr.split(',')
command=args[0]

while (command!="EXIT"):        
    if command=="LOGIN":  
        #登入    
        host='iquotetest.kgi.com.tw'
        port=8000
        uid=args[1]
        pwd=args[2]
        quotecomPy.quoteCom.Connect2Quote(host, port, uid, pwd, ' ', "")
    elif command=="LOGOUT":
        #登出
        quotecomPy.quoteCom.Logout()
    elif command=="SUBSCRIBE":
        #訂閱報價
        stocklist=args[1]        
        ##訂閱成交資料
        istatus = quotecomPy.quoteCom.SubQuotesMatch(stocklist)
        print("SubQuotesMatch istatus:[{v1}]".format(v1=istatus))     
        ##訂閱五檔資料
        istatus = quotecomPy.quoteCom.SubQuotesDepth(stocklist)
        print("SubQuotesDepth istatus:[{v1}]".format(v1=istatus))  
        ##訂閱盤中零股成交資料
        istatus = quotecomPy.quoteCom.SubQuotesMatchOdd(stocklist)
        print("SubQuotesMatchOdd istatus:[{v1}]".format(v1=istatus))  
        ##訂閱盤中零股五檔資料
        istatus = quotecomPy.quoteCom.SubQuotesDepthOdd(stocklist)
        print("SubQuotesDepthOdd istatus:[{v1}]".format(v1=istatus))  
    elif command=="UNSUBSCRIBE":
        #解除訂閱
        stocklist=args[1]
        ##解除訂閱成交資料
        istatus = quotecomPy.quoteCom.UnSubQuotesMatch(stocklist)
        print("UnSubQuotesMatch istatus:[{v1}]".format(v1=istatus))     
        ##解除訂閱五檔資料
        istatus = quotecomPy.quoteCom.UnSubQuotesDepth(stocklist)
        print("UnSubQuotesDepth istatus:[{v1}]".format(v1=istatus))  
        ##解除訂閱盤中零股成交資料
        istatus = quotecomPy.quoteCom.UnSubQuotesMatchOdd(stocklist)
        print("SubQuotesMatchOdd istatus:[{v1}]".format(v1=istatus))  
        ##解除訂閱盤中零股五檔資料
        istatus = quotecomPy.quoteCom.UnSubQuotesDepthOdd(stocklist)
        print("SubQuotesDepthOdd istatus:[{v1}]".format(v1=istatus))  
    elif command=="DOWNLOAD":
        #下載商品檔
        ##下載上巿商品檔
        rc=quotecomPy.quoteCom.RetriveProductTSE()         
        if (rc==0):
            print("下載上巿商品檔成功") 
        else:
            print("下載上巿商品檔失敗,Error:{err}".format(err=rc));
        ##下載上櫃商品檔
        rc=quotecomPy.quoteCom.RetriveProductOTC() 
        if (rc==0):
            print("下載上櫃商品檔成功") 
        else:
            print("下載上櫃商品檔失敗,Error:{err}".format(err=rc));
    elif command=="QUERYSTOCK":
        #查詢商品基本資料
        stockid=args[1]
        pkg=quotecomPy.quoteCom.GetProductSTOCK(stockid)
        print(pkg) 
        if (pkg==None):
            print("無法取得該商品明細,可能商品檔未下載或該商品不存在!!");
        else:
            Bull_Price = float(str(pkg.Bull_Price))/10000
            Ref_Price = float(str(pkg.Ref_Price))/10000
            Bear_Price = float(str(pkg.Bear_Price))/10000
            print("{mkt} {stockno} {stockname} 漲停價{bull},參考價:{ref},跌停價:{bear}".format(mkt=pkg.Market,stockno=pkg.StockNo,stockname=pkg.StockName,bull=Bull_Price,ref=Ref_Price, bear=Bear_Price)); 
    elif command=="LASTPRICE":
        #查詢最後價格,結果會傳到 quotecomPy.onQuoteRcvMessage        
        stockid=args[1]
        quotecomPy.quoteCom.RetriveLastPriceStock(stockid) 
        #查詢盤中零股最後價格
        quotecomPy.quoteCom.RetriveLastPriceStockOdd(stockid) 
    elif command=="SUBINDEX":
        #訂閱新編指數報價
        quotecomPy.quoteCom.SubQuotesNewIndex();
    elif command=="UNSUBINDEX":
        #解除訂閱新編指數報價
        quotecomPy.quoteCom.UnSubQuotesNewIndex();
    elif command=="LASTINDEX":
        #查詢最後指數,結果會傳到 quotecomPy.onQuoteRcvMessage  
        IndexID = args[1]
        ##上市最新指數查詢
        quotecomPy.quoteCom.RetriveLastNewIndex(IdxKind.IdxKind_TSE, IndexID);
        ##上櫃最新指數查詢
        quotecomPy.quoteCom.RetriveLastNewIndex(IdxKind.IdxKind_OTC, IndexID);

    inputstr = ''
    while (len(inputstr)<4):   
        inputstr = input('***請輸入指令:')
    
    args = inputstr.split(",")    
    command=args[0]

quotecomPy.quoteCom.Dispose()
