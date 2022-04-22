# -*- coding: utf-8 -*-
{
    'name': "Ordenes de Trabajo",

    'summary': """ Módulo de ordenes de trabajo """,

    'description': """
         Módulo para ordenes de trabajo
    """,

    'author': "",
    'website': "",

    'category': 'Uncategorized',
    'version': '0.1',

    'depends': ['base', 'sale'],

    'data': [
        'views/orden_trabajo_views_two.xml',
        'security/ir.model.access.csv',
    ],
}
