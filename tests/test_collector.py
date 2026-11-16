import unittest
from collector import extract_items, item_to_row, products_from
import test_library
import app


class ParserTest(unittest.TestCase):
    def item(self):
        return {'id':'7460373937537551634','desc':'Skincare serum #tiktokshop',
                'author':{'uniqueId':'test'},'video':{'duration':24},'stats':{'playCount':100,'diggCount':5}}

    def test_nested_search_response_and_id_preservation(self):
        item=self.item()
        result=extract_items({'data':[{'item':item},{'item':item}], 'other':{'id':'999'}})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['id'],'7460373937537551634')

    def test_keywords_do_not_confirm_commerce_or_market(self):
        row=item_to_row(self.item(),'US','serum')
        self.assertIsNone(row['is_commerce'])
        self.assertEqual(row['country'],'UNKNOWN')
        self.assertEqual(row['target_market'],'US')
        self.assertEqual(row['category'],'美妆个护')
        self.assertIsNone(row['estimated_sales'])
        self.assertIsNone(row['engagement_rate'])

    def test_explicit_commerce_and_products_without_guessed_prices(self):
        item=self.item();item['isECVideo']=1
        item['anchors']=[{'product_id':'1730228441641554287','product_name':'serum','price':1168}]
        row=item_to_row(item,'US','serum')
        self.assertTrue(row['is_commerce'])
        self.assertEqual(row['products'][0]['id'],'1730228441641554287')
        self.assertIsNone(row['products'][0]['price'])

    def test_ad_flag_alone_is_not_a_shopping_product(self):
        item=self.item();item['desc']='a funny story';item['isAd']=True
        self.assertIsNone(item_to_row(item,'US','test')['is_commerce'])
        self.assertEqual(products_from(item),[])


class CollectionPersistenceTest(unittest.TestCase):
    setUp = test_library.LibraryTest.setUp
    tearDown = test_library.LibraryTest.tearDown
    record = test_library.LibraryTest.record
    def test_refresh_keeps_existing_sales_and_product_sources(self):
        old=self.record(estimated_sales=12,views=100)
        app.import_rows([old])
        row=ParserTest().item();row['stats']['playCount']=200
        app.save_collected([item_to_row(row,'US','serum')])
        saved=app.get_video(row['id'])
        self.assertEqual(saved['estimated_sales'],12)
        self.assertEqual(saved['views'],200)
        self.assertEqual(saved['country'],'US')
        self.assertEqual(len(saved['products']),1)
        self.assertEqual(saved['field_sources']['estimated_sales'],old['source'])

    def test_target_market_filter_includes_unverified_but_labels_it(self):
        app.save_collected([item_to_row(ParserTest().item(),'US','serum')])
        records=app.filtered({'country':['US']})['items']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['country'],'UNKNOWN')
